from unittest import mock

import psycopg
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django_celery_beat.models import PeriodicTask

from core.db.tenancy import default_database, use_database
from core.services import Environment
from core.testing import ForgetDatabaseAliasesMixin
from saas.services import TenantService
from user.models import UserRole
from website.apps import DEFAULT_WEBSITE_ID
from website.models import Website

URL = "/saas/tenant-migrate/"
API_KEY = "test-saas-api-key"


def service():
    return TenantService(Environment(None))


@override_settings(SAAS_API_KEY=API_KEY)
class TenantMigrateTestCase(ForgetDatabaseAliasesMixin, TransactionTestCase):

    def setUp(self):
        super().setUp()
        # An empty database, unique per parallel test worker.
        self.dbname = f"{connection.settings_dict['NAME']}_migrated"
        service().drop_database(self.dbname)
        service().create_database(self.dbname)
        self.addCleanup(service().drop_database, self.dbname)

    def post(self, body=None, api_key=API_KEY, dbname=None):
        """ As the proxy forwards it: the domain designates the database. """
        return self.client.post(
            URL, body or {}, content_type="application/json",
            HTTP_X_API_KEY=api_key, HTTP_X_TENANT_DB=dbname or self.dbname,
        )

    def raw_connection(self):
        """ A session of another process, as a worker or a request would hold. """
        settings_dict = connection.settings_dict
        conn = psycopg.connect(
            dbname=self.dbname,
            user=settings_dict["USER"],
            password=settings_dict["PASSWORD"],
            host=settings_dict["HOST"],
            port=settings_dict["PORT"],
        )
        self.addCleanup(conn.close)
        return conn

    def test_migrate_then_nothing_left(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["dbname"], self.dbname)
        self.assertEqual(data["killed_connections"], 0)
        self.assertIn("user.0001_initial", data["applied"])
        self.assertIn("website.0001_initial", data["applied"])
        self.assert_system_data()

        # Hot and idempotent: run again while a session is open.
        session = self.raw_connection()
        response = self.post()
        self.assertEqual(response.json(), {"dbname": self.dbname, "killed_connections": 0, "applied": []})
        session.execute("SELECT 1")  # untouched

    def assert_system_data(self):
        """ What `populate --env system` loads: fixtures and periodic tasks. """
        with use_database(self.dbname):
            self.assertTrue(UserRole.objects.filter(pk="USERTYPE_ADMIN").exists())
            self.assertTrue(Website.objects.filter(pk=DEFAULT_WEBSITE_ID).exists())
            self.assertTrue(PeriodicTask.objects.filter(task="base.tasks.clear_sessions").exists())

    def test_system_data_restored(self):
        """ Run again, `populate` puts the system data back, and adds none twice. """
        self.post()
        with use_database(self.dbname):
            PeriodicTask.objects.filter(task="base.tasks.clear_sessions").delete()
            count = UserRole.objects.count()

        self.assertEqual(self.post().status_code, 200)

        self.assert_system_data()
        with use_database(self.dbname):
            self.assertEqual(UserRole.objects.count(), count)
            self.assertEqual(PeriodicTask.objects.filter(task="base.tasks.clear_sessions").count(), 1)

    def test_kill_connections(self):
        session = self.raw_connection()
        response = self.post({"kill_connections": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["killed_connections"], 1)
        with self.assertRaises(psycopg.OperationalError):
            session.execute("SELECT 1")

    def test_busy_database(self):
        self.post()
        # A transaction holding the migration table: the migration must give
        # up rather than wait behind it.
        session = self.raw_connection()
        session.execute("LOCK TABLE django_migrations IN ACCESS EXCLUSIVE MODE")
        with mock.patch.object(TenantService, "lock_timeout", "100ms"), self.assertLogs("saas.services", "ERROR"):
            response = self.post()

        self.assertEqual(response.status_code, 409)
        session.rollback()
        # Released: the setting did not stay on the connections of the pool.
        self.assertEqual(self.post().status_code, 200)

    def test_unknown_database(self):
        response = self.post(dbname=f"{self.dbname}_missing")
        self.assertEqual(response.status_code, 404)

    def test_without_header_the_database_of_the_settings(self):
        """ A single-tenant deployment, without a proxy. """
        response = self.client.post(URL, {}, content_type="application/json", HTTP_X_API_KEY=API_KEY)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dbname"], default_database())
        self.assertEqual(response.json()["applied"], [])

    def test_invalid_body(self):
        self.assertEqual(self.post({"dbname": self.dbname}).status_code, 422)
        self.assertEqual(self.post({"kill_connections": "maybe"}).status_code, 422)

    def test_api_key(self):
        self.assertEqual(self.post(api_key="wrong").status_code, 401)
        with override_settings(SAAS_API_KEY=""):
            self.assertEqual(self.post().status_code, 404)
