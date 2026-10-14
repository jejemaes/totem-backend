from unittest import mock

from django.db import connection
from django.test import TransactionTestCase, override_settings

from core.db.tenancy import use_database
from core.services import Environment
from core.testing import ForgetDatabaseAliasesMixin
from saas.services import TenantService
from user.choices import UserType
from user.models import User
from website.apps import DEFAULT_WEBSITE_ID
from website.models import Website

URL = "/saas/tenant-create/"
API_KEY = "test-saas-api-key"


def database_exists(db_name):
    return TenantService(Environment(None)).database_exists(db_name)


def drop_database(db_name):
    TenantService(Environment(None)).drop_database(db_name)


@override_settings(SAAS_API_KEY=API_KEY)
class TenantCreateTestCase(ForgetDatabaseAliasesMixin, TransactionTestCase):
    """ `TransactionTestCase`: the view switches to the new database, which a
    `TestCase` transaction would refuse. """

    def setUp(self):
        super().setUp()
        # Unique per parallel test worker, as is the test database.
        self.dbname = f"{connection.settings_dict['NAME']}_created"
        self.addCleanup(drop_database, self.dbname)
        self.body = {
            "email": "admin@acme.com",
            "name": "ACME",
            "password": "a-Long-and-unusual-passphrase",
        }

    def post(self, body=None, api_key=API_KEY, dbname=None):
        """ As the proxy forwards it: the domain designates the database. """
        headers = {"HTTP_X_TENANT_DB": dbname or self.dbname}
        if api_key is not None:
            headers["HTTP_X_API_KEY"] = api_key
        return self.client.post(URL, body if body is not None else self.body, content_type="application/json", **headers)

    def test_create_tenant(self):
        response = self.post()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), {"dbname": self.dbname, "name": "ACME", "email": "admin@acme.com"})
        self.assertTrue(database_exists(self.dbname))
        with use_database(self.dbname):
            admin = User.objects.get(username="admin@acme.com")
            self.assertEqual(admin.email, "admin@acme.com")
            self.assertTrue(admin.check_password("a-Long-and-unusual-passphrase"))
            self.assertTrue(admin.is_superuser)
            self.assertTrue(admin.is_staff)
            self.assertEqual(admin.user_type, UserType.ADMIN)
            self.assertEqual(list(admin.roles.values_list("pk", flat=True)), ["USERTYPE_ADMIN"])
            self.assertEqual(Website.objects.get(pk=DEFAULT_WEBSITE_ID).name, "ACME")
        # Nothing written in the database of the request.
        self.assertFalse(User.objects.filter(username="admin@acme.com").exists())

    def test_disabled_without_api_key_setting(self):
        with override_settings(SAAS_API_KEY=""):
            self.assertEqual(self.post().status_code, 404)
        self.assertFalse(database_exists(self.dbname))

    def test_wrong_or_missing_api_key(self):
        self.assertEqual(self.post(api_key="wrong").status_code, 401)
        self.assertEqual(self.post(api_key=None).status_code, 401)
        self.assertFalse(database_exists(self.dbname))

    def test_get_not_allowed(self):
        response = self.client.get(URL, HTTP_X_API_KEY=API_KEY)
        self.assertEqual(response.status_code, 405)

    def test_invalid_bodies(self):
        cases = {
            "email": {"email": "not an email"},
            "name": {"name": ""},
            "password": {"password": "123"},
        }
        for field, change in cases.items():
            with self.subTest(field=field):
                response = self.post({**self.body, **change})
                self.assertEqual(response.status_code, 422)
                self.assertIn(field, [error["loc"][-1] for error in response.json()["detail"]])
        response = self.post({key: value for key, value in self.body.items() if key != "email"})
        self.assertEqual(response.status_code, 422)
        response = self.post({**self.body, "unexpected": 1})
        self.assertEqual(response.status_code, 422)
        self.assertFalse(database_exists(self.dbname))

    def test_no_tenant_designated(self):
        """ Without the header, the database of the settings is not created. """
        response = self.client.post(URL, self.body, content_type="application/json", HTTP_X_API_KEY=API_KEY)
        self.assertEqual(response.status_code, 400)

    def test_invalid_database_name(self):
        # Refused by the middleware, before the view.
        self.assertEqual(self.post(dbname="Bad-Name").status_code, 404)
        self.assertFalse(database_exists("Bad-Name"))

    def test_existing_database(self):
        response = self.post(dbname=connection.settings_dict["NAME"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": f"The database {connection.settings_dict['NAME']!r} already exists."})

    def test_failure_drops_the_database(self):
        with mock.patch.object(TenantService, "rename_website", side_effect=RuntimeError("boom")), \
                self.assertLogs("saas.services", "ERROR"):
            response = self.post()

        self.assertEqual(response.status_code, 500)
        self.assertFalse(database_exists(self.dbname))
        # The same call can be made again.
        self.assertEqual(self.post().status_code, 201)
