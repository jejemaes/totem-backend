from django.core.management import call_command
from django.db import connection, connections

from core.db.tenancy import use_database


class TenantDatabaseTestMixin:
    """ Gives a `TransactionTestCase` a second, migrated tenant database.

    Its name, `tenant_db`, derives from the test database, so that parallel
    test workers each get their own. It is created and migrated once per test
    class (a few seconds), then dropped.

    Not for a `TestCase`: its transaction on `default` forbids switching to
    another database (`DatabaseSwitchError`).
    """

    tenant_db_suffix = "tenant"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_db = f"{connection.settings_dict['NAME']}_{cls.tenant_db_suffix}"
        with connection._nodb_cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{cls.tenant_db}"')
            cursor.execute(f'CREATE DATABASE "{cls.tenant_db}"')
        call_command("tenant_migrate", cls.tenant_db, verbosity=0)

    @classmethod
    def tearDownClass(cls):
        forget_database(cls.tenant_db)
        with connection._nodb_cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{cls.tenant_db}"')
        super().tearDownClass()

    def tearDown(self):
        # `TransactionTestCase` only flushes the databases of `databases`.
        with use_database(self.tenant_db):
            call_command("flush", interactive=False, verbosity=0)
        super().tearDown()


class ForgetDatabaseAliasesMixin:
    """ Forget, after each test, the database aliases it created.

    A request designating a database (`X-Tenant-Db`) creates its alias. Left
    behind, it breaks the teardown of the test case: Django removes its
    "queries not allowed" guards from every alias it iterates, but only put
    them on the aliases that existed when the test case started.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(self.forget_new_aliases, connections.tenant_aliases())

    def forget_new_aliases(self, known):
        for alias in connections.tenant_aliases() - known:
            forget_database(alias)


def forget_database(db_name):
    """ Close the alias of a database and remove it, so that it can be dropped. """
    connections.forget_database(db_name)
