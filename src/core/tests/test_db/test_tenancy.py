import logging
import time
from unittest import mock

from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connection, connections, transaction
from django.utils.connection import ConnectionDoesNotExist
from django.db.backends.postgresql.base import DatabaseWrapper
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from base.models import Country
from core.db.routers import TenantRouter
from core.db.tenancy import (
    DatabaseNameError,
    DatabaseNameFilter,
    DatabaseSwitchError,
    TenantConnectionHandler,
    current_database,
    default_database,
    use_database,
)
from core.services import Environment


class CurrentDatabaseTestCase(SimpleTestCase):

    def test_handler_is_installed(self):
        self.assertIsInstance(connections, TenantConnectionHandler)

    def test_default_without_context(self):
        self.assertEqual(current_database(), settings.DATABASES[DEFAULT_DB_ALIAS]["NAME"])
        self.assertEqual(current_database(), default_database())

    def test_nesting_restores_enclosing_database(self):
        with use_database("tenant_a"):
            self.assertEqual(current_database(), "tenant_a")
            with use_database("tenant_b"):
                self.assertEqual(current_database(), "tenant_b")
            self.assertEqual(current_database(), "tenant_a")
        self.assertEqual(current_database(), default_database())

    def test_restored_on_exception(self):
        with self.assertRaises(ZeroDivisionError):
            with use_database("tenant_a"):
                1 / 0
        self.assertEqual(current_database(), default_database())

    def test_invalid_names(self):
        for db_name in ["", "Tenant", "1tenant", "tenant-a", "../tenant", "tenant.a", "a" * 64, None]:
            with self.subTest(db_name=db_name), self.assertRaises(DatabaseNameError):
                with use_database(db_name):
                    pass

    def test_static_alias_refused(self):
        with self.assertRaises(DatabaseNameError):
            with use_database(DEFAULT_DB_ALIAS):
                pass
        with mock.patch.dict(settings.DATABASES, {"saas_base": dict(settings.DATABASES["default"])}):
            with self.assertRaises(DatabaseNameError):
                with use_database("saas_base"):
                    pass

    def test_propagates_through_sync_to_async(self):
        async def read_in_thread():
            with use_database("tenant_a"):
                return await sync_to_async(current_database)()

        self.assertEqual(async_to_sync(read_in_thread)(), "tenant_a")

    def test_environment_db_name(self):
        env = Environment(None)
        self.assertEqual(env.db_name, default_database())
        with use_database("tenant_a"):
            self.assertEqual(env.db_name, "tenant_a")

    def test_log_records_carry_db_name(self):
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
        with use_database("tenant_a"):
            DatabaseNameFilter().filter(record)
        self.assertEqual(record.db_name, "tenant_a")


    def test_router_keeps_apps_out_of_catalog(self):
        router = TenantRouter()
        with mock.patch.dict(settings.DATABASES, {"saas_base": dict(settings.DATABASES["default"])}):
            self.assertIs(router.allow_migrate("saas_base", "user"), False)
            self.assertIsNone(router.allow_migrate(default_database(), "user"))


class DefaultAliasTestCase(SimpleTestCase):
    """ Outside of a transaction: a `TestCase` would refuse the switches. """

    def tearDown(self):
        # Never connected: only its alias was created, which later test
        # classes would otherwise see in `connections`.
        forget_database("tenant_a")
        super().tearDown()

    def test_default_follows_the_context(self):
        with use_database("tenant_a"):
            self.assertEqual(connections[DEFAULT_DB_ALIAS].alias, "tenant_a")
            self.assertEqual(connections[DEFAULT_DB_ALIAS].settings_dict["NAME"], "tenant_a")
            # Same credentials and pool as the template, the pool named after it.
            settings_dict = connections[DEFAULT_DB_ALIAS].settings_dict
            template = settings.DATABASES[DEFAULT_DB_ALIAS]
            for key in ["USER", "PASSWORD", "HOST", "PORT"]:
                self.assertEqual(settings_dict[key], template[key])
            self.assertEqual(
                settings_dict["OPTIONS"]["pool"],
                {**template["OPTIONS"]["pool"], "name": "tenant_a"},
            )
            self.assertNotIn("name", template["OPTIONS"]["pool"])

    def test_iteration_yields_default_not_its_database(self):
        with use_database("tenant_a"):
            connections[DEFAULT_DB_ALIAS]  # materialize the alias
        aliases = list(connections)
        self.assertIn(DEFAULT_DB_ALIAS, aliases)
        self.assertNotIn(current_database(), aliases)
        self.assertIn("tenant_a", aliases)
        with use_database("tenant_a"):
            self.assertNotIn("tenant_a", list(connections))


class DefaultConnectionTestCase(TestCase):

    def test_default_is_the_current_database_connection(self):
        current = current_database()
        self.assertIs(connections[DEFAULT_DB_ALIAS], connections[current])
        # Same database, same connection: an `atomic()` on one covers the other.
        self.assertEqual(connections[DEFAULT_DB_ALIAS].alias, current)
        self.assertEqual(connection.alias, current)

    def test_all_initialized_only_includes_current_connection(self):
        connection.ensure_connection()
        self.assertIn(connections[DEFAULT_DB_ALIAS], connections.all(initialized_only=True))

    def test_switch_refused_inside_transaction(self):
        # A `TestCase` runs each test in a transaction on `default`.
        self.assertTrue(connection.in_atomic_block)
        with self.assertRaises(DatabaseSwitchError):
            with use_database("tenant_a"):
                pass
        # Selecting the same database again is harmless.
        with use_database(current_database()):
            with transaction.atomic():
                pass

    def test_unknown_alias_syntax(self):
        with self.assertRaises(ConnectionDoesNotExist):
            connections["Not a database"]

    def test_tenant_migrate_refuses_database_option(self):
        with self.assertRaises(CommandError):
            call_command("tenant_migrate", "tenant_a", database="other", verbosity=0)


class TenantIsolationTestCase(TransactionTestCase):
    """ Two real databases: the data of one is not visible from the other. """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Unique per parallel test worker, as is the test database.
        cls.other = f"{connection.settings_dict['NAME']}_tenancy"
        with connection._nodb_cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{cls.other}"')
            cursor.execute(f'CREATE DATABASE "{cls.other}"')
        call_command("tenant_migrate", cls.other, verbosity=0)

    @classmethod
    def tearDownClass(cls):
        forget_database(cls.other)
        with connection._nodb_cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{cls.other}"')
        super().tearDownClass()

    def tearDown(self):
        with use_database(self.other):
            Country.objects.all().delete()
        super().tearDown()

    def test_data_isolation(self):
        Country.objects.create(code="BE", name="Belgium")
        with use_database(self.other):
            self.assertFalse(Country.objects.filter(code="BE").exists())
            Country.objects.create(code="FR", name="France")
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database()")
                self.assertEqual(cursor.fetchone()[0], self.other)
        self.assertFalse(Country.objects.filter(code="FR").exists())
        self.assertTrue(Country.objects.filter(code="BE").exists())

    def test_transaction_stays_on_its_database(self):
        with use_database(self.other):
            with self.assertRaises(ZeroDivisionError):
                with transaction.atomic():
                    Country.objects.create(code="FR", name="France")
                    1 / 0
            self.assertFalse(Country.objects.filter(code="FR").exists())

    def test_async_unit_of_work(self):
        async def create_in_other():
            with use_database(self.other):
                await Country.objects.acreate(code="FR", name="France")

        async_to_sync(create_in_other)()
        self.assertFalse(Country.objects.filter(code="FR").exists())
        with use_database(self.other):
            self.assertTrue(Country.objects.filter(code="FR").exists())

    def test_one_pool_per_database(self):
        Country.objects.exists()
        with use_database(self.other):
            Country.objects.exists()
        self.assertIn(current_database(), DatabaseWrapper._connection_pools)
        self.assertIn(self.other, DatabaseWrapper._connection_pools)
        self.assertIsNot(
            DatabaseWrapper._connection_pools[current_database()],
            DatabaseWrapper._connection_pools[self.other],
        )

    def test_idle_pool_eviction(self):
        with use_database(self.other):
            Country.objects.exists()
            connection.close()  # back to the pool
        Country.objects.exists()
        current_pool = DatabaseWrapper._connection_pools[current_database()]
        # Keep a connection of the current database borrowed: never evicted.
        with transaction.atomic():
            Country.objects.exists()
            evicted = connections.evict_idle_pools(now=time.monotonic() + 3600)
        self.assertIn(self.other, evicted)
        self.assertNotIn(self.other, DatabaseWrapper._connection_pools)
        self.assertNotIn(current_database(), evicted)
        self.assertIs(DatabaseWrapper._connection_pools[current_database()], current_pool)

        # Created again on next use.
        with use_database(self.other):
            self.assertFalse(Country.objects.exists())
        self.assertIn(self.other, DatabaseWrapper._connection_pools)


def forget_database(db_name):
    """ Close and drop the alias of a database, so that it can be dropped. """
    conn = connections.get_initialized(db_name)
    if conn is not None:
        conn.close()
        del connections[db_name]
    pool = DatabaseWrapper._connection_pools.pop(db_name, None)
    if pool is not None:
        pool.close()
    with connections._lock:
        connections.settings.pop(db_name, None)
        connections._tenant_aliases.discard(db_name)
