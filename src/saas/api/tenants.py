from ninja.errors import HttpError

from core.api import BaseController, route
from core.db.tenancy import current_database, selected_database
from saas.schemas import TenantCreateSchema, TenantMigrateSchema, TenantMigrationSchema, TenantSchema
from saas.security import SaasApiKey
from saas.services import (
    DatabaseBusy,
    DatabaseExists,
    DatabaseNotFound,
    TenantCreationFailed,
    TenantMigrationFailed,
    TenantService,
)

from .root import saas_api

__all__ = ["TenantController"]


class TenantController(BaseController):
    """ The tenants of the platform, for its operator.

    A `BaseController` with a service but no model: a tenant is a database, not
    a row (see `TenantService`). Called server to server with the operator key
    (`SaasApiKey`), so no scope or permission on top of it.
    """

    api = saas_api
    path_prefix = "/"
    auth = [SaasApiKey()]

    @route.post(
        "/tenant-create/",
        response={201: TenantSchema},
        operation_id="tenantCreate",
        summary="Create a tenant",
        tags=["Tenant"],
    )
    async def create(self, request, body: TenantCreateSchema):
        # The database is the one the domain designates: the proxy declares the
        # tenant and its domain first, then calls this endpoint on that domain.
        # Nothing reaches the database before this view (the key is checked
        # without it), which is what lets the request run "on" a database that
        # does not exist yet.
        #
        # A designated database is required: on the default one, an operator
        # call bypassing the proxy would create the database of the settings,
        # which a multi-tenant deployment keeps missing on purpose.
        db_name = selected_database()
        if db_name is None:
            raise HttpError(400, "No tenant designated: call this endpoint on the domain of the tenant.")
        # Synchronous for the caller: created, migrated and populated within
        # the request (a few seconds; nginx gives it 3 minutes).
        try:
            await request.env.get(TenantService).create(db_name, body)
        except DatabaseExists:
            raise HttpError(409, f"The database {db_name!r} already exists.")
        except TenantCreationFailed:
            raise HttpError(500, "The tenant could not be created.")
        return 201, {"dbname": db_name, "name": body.name, "email": body.email}

    @route.post(
        "/tenant-migrate/",
        response=TenantMigrationSchema,
        operation_id="tenantMigrate",
        summary="Migrate a tenant",
        tags=["Tenant"],
    )
    async def migrate(self, request, body: TenantMigrateSchema):
        # The database the domain designates, or the one of the settings in a
        # single-tenant deployment (without a proxy). Synchronous too, under the
        # same 3 minutes of nginx. Hot by default; the proxy keeps this endpoint
        # reachable when it takes the tenant offline, for a migration with
        # `kill_connections`.
        db_name = current_database()
        try:
            killed, applied = await request.env.get(TenantService).migrate(
                db_name, kill_connections=body.kill_connections
            )
        except DatabaseNotFound:
            raise HttpError(404, f"No database {db_name!r}.")
        except DatabaseBusy:
            raise HttpError(409, "A migration waited too long for a lock: the database is busy, retry.")
        except TenantMigrationFailed:
            raise HttpError(500, "The migration failed.")
        return {"dbname": db_name, "killed_connections": killed, "applied": applied}
