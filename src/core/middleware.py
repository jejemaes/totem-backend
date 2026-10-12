import contextlib
import logging

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpResponseNotFound

from core.db.tenancy import DatabaseNameError, use_database, validate_database_name

logger = logging.getLogger(__name__)

TENANT_DB_HEADER = "X-Tenant-Db"


class TenantMiddleware:
    """ Run the request on the database named by the `X-Tenant-Db` header.

    The multi-tenant proxy resolves the tenant from the domain and always sets
    this header, overwriting any value sent by the client: it is trusted as is,
    and the catalog of tenants is not looked up again. The backend must
    therefore only be reachable through the proxy.

    Without the header, the request runs on the database of the settings (a
    single-tenant deployment). A header that is not a database name answers a
    404, as an unknown domain does at the proxy.

    First in `MIDDLEWARE`, so that every other middleware (sessions, auth, ...)
    runs on the tenant database too. The body of a streaming response is read
    after this middleware returns, outside of the tenant database: none of the
    views stream today.
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if iscoroutinefunction(self.get_response):
            markcoroutinefunction(self)

    def __call__(self, request):
        if iscoroutinefunction(self):
            return self.__acall__(request)
        database = self.select_database(request)
        if database is None:
            return HttpResponseNotFound()
        with database:
            return self.get_response(request)

    async def __acall__(self, request):
        database = self.select_database(request)
        if database is None:
            return HttpResponseNotFound()
        # The context variable is copied into the threads running the sync
        # code (`sync_to_async`), so they see the database selected here.
        with database:
            return await self.get_response(request)

    def select_database(self, request):
        """ The context to run the request in, or `None` to refuse it. """
        db_name = request.headers.get(TENANT_DB_HEADER)
        if not db_name:
            return contextlib.nullcontext()
        try:
            # Here, not on entering `use_database()` (which checks it too), so
            # that a bad name is answered rather than raised.
            validate_database_name(db_name)
        except DatabaseNameError:
            logger.warning("Invalid %s header: %r", TENANT_DB_HEADER, db_name)
            return None
        return use_database(db_name)
