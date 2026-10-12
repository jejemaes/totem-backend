from datetime import timedelta

from asgiref.sync import async_to_sync
from django.db import close_old_connections, connections
from django.test import AsyncClient, TransactionTestCase
from django.utils import timezone

from base.models import Country
from core.db.tenancy import current_database, default_database, use_database
from core.testing import APITestCaseMixin, TenantDatabaseTestMixin
from oauth.models import AccessToken, OAuthApp
from user.choices import UserType
from user.models import User

COUNTRIES_URL = "/api/v1/countries/"


def create_token(token):
    """ A user token reading countries, in the current database. """
    application = OAuthApp.objects.create(
        name="Application for Test",
        client_type=OAuthApp.CLIENT_CONFIDENTIAL,
        authorization_grant_type=OAuthApp.GRANT_CLIENT_CREDENTIALS,
    )
    user = User.objects.create(
        username=f"{token}@totem.test",
        email=f"{token}@totem.test",
        user_type=UserType.INTERNAL,
    )
    return AccessToken.objects.create(
        user=user,
        application=application,
        token=token,
        scope="totem.country.read",
        expires=timezone.now() + timedelta(days=1),
    )


class TenantMiddlewareTestCase(TenantDatabaseTestMixin, APITestCaseMixin, TransactionTestCase):
    """ `TransactionTestCase`: a request on another database switches to it,
    which a `TestCase` transaction would refuse. """

    def setUp(self):
        super().setUp()
        Country.objects.create(code="BE", name="Belgium")
        create_token("default_token")
        with use_database(self.tenant_db):
            Country.objects.create(code="FR", name="France")
            create_token("tenant_token")

    def list_countries(self, token, **headers):
        """ The status code, and the codes of the countries listed. """
        response = self.do_api_request(COUNTRIES_URL, "GET", token, **headers)
        if response.status_code != 200:
            return response.status_code, None
        return response.status_code, [item["id"] for item in response.json()["results"]]

    def test_header_selects_the_database(self):
        status, codes = self.list_countries("tenant_token", HTTP_X_TENANT_DB=self.tenant_db)
        self.assertEqual(status, 200)
        self.assertEqual(codes, ["FR"])

    def test_without_header_default_database(self):
        status, codes = self.list_countries("default_token")
        self.assertEqual(status, 200)
        self.assertEqual(codes, ["BE"])

    def test_token_only_valid_in_its_database(self):
        status, dummy = self.list_countries("default_token", HTTP_X_TENANT_DB=self.tenant_db)
        self.assertEqual(status, 401)
        status, dummy = self.list_countries("tenant_token")
        self.assertEqual(status, 401)

    def test_invalid_header_is_not_found(self):
        for value in ["Tenant", "../media", "default", "a" * 64]:
            with self.subTest(value=value):
                response = self.do_api_request(
                    COUNTRIES_URL, "GET", "default_token", HTTP_X_TENANT_DB=value
                )
                self.assertEqual(response.status_code, 404)

    def test_async_request(self):
        """ Under ASGI, the middleware chain is async. """
        response = async_to_sync(AsyncClient().get)(
            COUNTRIES_URL,
            headers={"Authorization": "Bearer tenant_token", "X-Tenant-Db": self.tenant_db},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], ["FR"])

    def test_database_restored_after_request(self):
        self.list_countries("tenant_token", HTTP_X_TENANT_DB=self.tenant_db)
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
