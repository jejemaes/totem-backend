from asgiref.sync import async_to_sync
from django.db import close_old_connections, connections
from django.test import AsyncClient, TransactionTestCase

from authentication.testing import mint_access_token
from base.models import Country
from core.db.tenancy import current_database, default_database, use_database
from core.testing import APITestCaseMixin, TenantDatabaseTestMixin
from user.choices import UserType
from user.models import User

COUNTRIES_URL = "/api/v1/countries/"


def create_token(name):
    """ A user token reading countries, minted for the current database.

    What makes a token local to one tenant is no longer where its row lives --
    there is no row. `encode_access_token` stamps `current_database()` into the
    `db` claim and the decoder refuses a claim that does not match, which is why
    this has to be called inside the `use_database` block of its tenant.
    """
    user = User.objects.create(
        username=f"{name}@totem.test",
        email=f"{name}@totem.test",
        user_type=UserType.INTERNAL,
    )
    return mint_access_token(user, ["totem.country.read"])


class TenantMiddlewareTestCase(TenantDatabaseTestMixin, APITestCaseMixin, TransactionTestCase):
    """ `TransactionTestCase`: a request on another database switches to it,
    which a `TestCase` transaction would refuse. """

    def setUp(self):
        super().setUp()
        Country.objects.create(code="BE", name="Belgium")
        self.default_token = create_token("default")
        with use_database(self.tenant_db):
            Country.objects.create(code="FR", name="France")
            self.tenant_token = create_token("tenant")

    def list_countries(self, token, **headers):
        """ The status code, and the codes of the countries listed. """
        response = self.do_api_request(COUNTRIES_URL, "GET", token, **headers)
        if response.status_code != 200:
            return response.status_code, None
        return response.status_code, [item["id"] for item in response.json()["results"]]

    def test_header_selects_the_database(self):
        status, codes = self.list_countries(self.tenant_token, HTTP_X_TENANT_DB=self.tenant_db)
        self.assertEqual(status, 200)
        self.assertEqual(codes, ["FR"])

    def test_without_header_default_database(self):
        status, codes = self.list_countries(self.default_token)
        self.assertEqual(status, 200)
        self.assertEqual(codes, ["BE"])

    def test_token_only_valid_in_its_database(self):
        """ The property the `db` claim exists for.

        The signing key is shared by every tenant, so each of these tokens is
        cryptographically valid against the other database. Only the claim
        separates them.
        """
        status, dummy = self.list_countries(self.default_token, HTTP_X_TENANT_DB=self.tenant_db)
        self.assertEqual(status, 401)
        status, dummy = self.list_countries(self.tenant_token)
        self.assertEqual(status, 401)

    def test_invalid_header_is_not_found(self):
        for value in ["Tenant", "../media", "default", "a" * 64]:
            with self.subTest(value=value):
                response = self.do_api_request(
                    COUNTRIES_URL, "GET", self.default_token, HTTP_X_TENANT_DB=value
                )
                self.assertEqual(response.status_code, 404)

    def test_async_request(self):
        """ Under ASGI, the middleware chain is async. """
        response = async_to_sync(AsyncClient().get)(
            COUNTRIES_URL,
            headers={
                "Authorization": f"Bearer {self.tenant_token}",
                "X-Tenant-Db": self.tenant_db,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], ["FR"])

    def test_database_restored_after_request(self):
        self.list_countries(self.tenant_token, HTTP_X_TENANT_DB=self.tenant_db)
        self.assertEqual(current_database(), default_database())

    def test_end_of_request_releases_tenant_connection(self):
        """ `request_finished` runs after the middleware, outside of the tenant
        database: it must still close the tenant connection of the thread, back
        to its pool. (The test client disconnects that handler, hence the
        direct call.) """
        with use_database(self.tenant_db):
            Country.objects.exists()
        connection = connections.get_initialized(self.tenant_db)
        self.assertIsNotNone(connection.connection)

        close_old_connections()

        self.assertIsNone(connection.connection)
