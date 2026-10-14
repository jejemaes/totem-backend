import io
import logging

from asgiref.sync import sync_to_async
from django.apps import apps
from django.core.management import call_command
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.migrations.recorder import MigrationRecorder
from django.db.utils import ProgrammingError
from psycopg.errors import LockNotAvailable

from core.db.tenancy import use_database, validate_database_name
from core.services import Service
from saas.schemas import TenantCreateSchema
from user.choices import UserType
from website.apps import DEFAULT_WEBSITE_ID

logger = logging.getLogger(__name__)

ADMIN_ROLE_ID = "USERTYPE_ADMIN"


class DatabaseExists(Exception):
    """ A database of that name already exists on the server. """


class TenantCreationFailed(Exception):
    """ A step of the creation failed; the database was dropped. """


class DatabaseNotFound(Exception):
    """ No database of that name on the server. """


class DatabaseBusy(Exception):
    """ The migration waited too long for a lock (`lock_timeout`). """


class TenantMigrationFailed(Exception):
    """ A migration, or the system data after them, failed; the migrations
    before it stay applied. """


class TenantService(Service):
    """ Creation of the database of a tenant: its schema, its system data, its
    administrator.

    A `Service` bound to no model: a tenant is a database, not a row, and its
    catalog belongs to the proxy. The data of the new database is written with
    the ORM directly, as `populate` does: no user acts there yet, so there is no
    environment whose access rules would apply. The acting environment is the
    one of the operator's request, on the database of that request.
    """

    async def create(self, db_name: str, data: TenantCreateSchema) -> None:
        """ Create, migrate and populate the database, and add its administrator.

        All or nothing: if any step fails once the database exists, it is
        dropped, so that the call can be made again (`TenantCreationFailed`).
        One hop to the sync world for the whole unit of work, as the other
        services do: the database commands are sync.
        """
        await sync_to_async(self._create)(db_name, data)

    def _create(self, db_name: str, data: TenantCreateSchema) -> None:
        validate_database_name(db_name)
        self.create_database(db_name)
        try:
            with use_database(db_name):
                output = io.StringIO()
                call_command("migrate", interactive=False, verbosity=0, stdout=output)
                call_command("populate", env="system", verbosity=0, stdout=output)
                with transaction.atomic():
                    self.create_admin(data.email, data.password)
                    self.rename_website(data.name)
        except Exception as exc:
            logger.exception("Creation of the tenant database %s failed, dropping it", db_name)
            self.drop_database(db_name)
            raise TenantCreationFailed(db_name) from exc
        logger.info("Tenant database %s created", db_name)

    # How long a migration waits for a lock before giving up. Waiting longer
    # would stack every query on that table behind it: the site of the tenant
    # would freeze for as long, rather than the migration being retried.
    lock_timeout = "5s"

    async def migrate(self, db_name: str, kill_connections: bool = False) -> tuple[int, list[str]]:
        """ Migrate the database of a tenant, while it serves (hot), then load
        its system data (`populate --env system`).

        Safe when the migrations are backward compatible with the code still
        running (expand first, contract once deployed). With `kill_connections`,
        the sessions open on the database are terminated first: for a migration
        that must not run alongside them, once the proxy took the tenant
        offline. Returns the number of sessions terminated and the migrations
        applied (`app.name`).
        """
        return await sync_to_async(self._migrate)(db_name, kill_connections)

    def _migrate(self, db_name, kill_connections):
        validate_database_name(db_name)
        if not self.database_exists(db_name):
            raise DatabaseNotFound(db_name)
        killed = self.kill_connections(db_name) if kill_connections else 0

        with use_database(db_name):
            connection = connections[DEFAULT_DB_ALIAS]
            try:
                # First: reading the migration table may wait for a lock too.
                self._set_lock_timeout(connection, self.lock_timeout)
                before = set(MigrationRecorder(connection).applied_migrations())
                output = io.StringIO()
                call_command("migrate", interactive=False, verbosity=0, stdout=output)
                # Then the system data of the new code: its fixtures, its
                # periodic tasks (`populate_system`). Idempotent; the rows of
                # the system fixtures are reset to their fixture values.
                call_command("populate", env="system", verbosity=0, stdout=output)
            except Exception as exc:
                logger.exception("Migration of the tenant database %s failed", db_name)
                if isinstance(exc.__cause__, LockNotAvailable):
                    raise DatabaseBusy(db_name) from exc
                raise TenantMigrationFailed(db_name) from exc
            finally:
                self._reset_lock_timeout(connection, db_name)
            applied = set(MigrationRecorder(connection).applied_migrations()) - before

        logger.info("Tenant database %s migrated: %d migration(s)", db_name, len(applied))
        return killed, sorted(f"{app}.{name}" for app, name in applied)

    def kill_connections(self, db_name) -> int:
        """ Terminate every session on the database but ours (we are connected
        to the maintenance database). The pools of the other processes discover
        it when they next hand a connection out (`CONN_HEALTH_CHECKS`). """
        connections.forget_database(db_name)
        with connections[DEFAULT_DB_ALIAS]._nodb_cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FILTER (WHERE pg_terminate_backend(pid)) FROM pg_stat_activity"
                " WHERE datname = %s AND pid <> pg_backend_pid()",
                [db_name],
            )
            killed = cursor.fetchone()[0]
        logger.warning("Terminated %d session(s) on the tenant database %s", killed, db_name)
        return killed

    def _set_lock_timeout(self, connection, value):
        # `set_config` rather than `SET`: the value is a bound parameter, which
        # `SET` does not accept.
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('lock_timeout', %s, false)", [value])

    def _reset_lock_timeout(self, connection, db_name):
        """ The setting belongs to the session, which goes back to the pool:
        reset it, or drop the connections of this process if that fails. """
        try:
            with connection.cursor() as cursor:
                cursor.execute("RESET lock_timeout")
        except Exception:
            connections.forget_database(db_name)

    # Content of the new database (run inside it)

    def create_admin(self, email, password):
        User = apps.get_model("user", "User")
        admin = User(
            username=email,
            email=email,
            user_type=UserType.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        admin.set_password(password)
        admin.save()
        admin.roles.add(ADMIN_ROLE_ID)
        return admin

    def rename_website(self, name):
        """ The website created by `populate`, named after the tenant. """
        Website = apps.get_model("website", "Website")
        Website.objects.filter(pk=DEFAULT_WEBSITE_ID).update(name=name)

    # Databases (on the maintenance database, with the credentials of the settings)

    def database_exists(self, db_name) -> bool:
        with connections[DEFAULT_DB_ALIAS]._nodb_cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [db_name])
            return cursor.fetchone() is not None

    def create_database(self, db_name):
        """ `CREATE DATABASE`, owned by the user of the settings. """
        connection = connections[DEFAULT_DB_ALIAS]
        if self.database_exists(db_name):
            raise DatabaseExists(db_name)
        with connection._nodb_cursor() as cursor:
            try:
                cursor.execute(f"CREATE DATABASE {connection.ops.quote_name(db_name)} ENCODING 'UTF8'")
            except ProgrammingError as exc:
                # Created by a concurrent call since the check above.
                if self.database_exists(db_name):
                    raise DatabaseExists(db_name) from exc
                raise

    def drop_database(self, db_name):
        """ `DROP DATABASE`, after closing what this process holds on it.
        `FORCE` (Postgres 13+) ends the sessions of the other processes too. """
        connection = connections[DEFAULT_DB_ALIAS]
        connections.forget_database(db_name)
        with connection._nodb_cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS {connection.ops.quote_name(db_name)} WITH (FORCE)")
