"""One Postgres database per tenant, behind the single `default` alias.

The database a unit of work runs on is held by a context variable, set with
`use_database()`. `django.db.connections["default"]` resolves it on every
access, so everything reaching the database through `default` follows it:
querysets, `transaction.atomic()` without `using`, the raw `connection.cursor()`
and the third-party apps alike. Without an active database, `default` is the
database named in `settings.DATABASES["default"]`.

Rejected alternative: one alias per database selected by a `DATABASE_ROUTER`.
A router is only asked by the ORM; `atomic()` without `using`, the raw
`connection` and `TestCase` would all stay on the real `default` database, and
the writes of a service would silently run outside of its transaction.

Each database gets its own alias, named after the database and created on first
use from the `default` entry (same credentials, other `NAME`). The connection
pool of Django is keyed by alias, so this gives one lazily created pool per
database with no change to the backend.
"""
import contextlib
import copy
import logging
import re
import threading
import time
import typing as t
from contextvars import ContextVar

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS
from django.db.utils import ConnectionHandler

from core.utils.various import env

logger = logging.getLogger(__name__)

# A Postgres identifier, lowercase only. The name also prefixes the filestore
# paths and the cache keys, so it must stay safe there too: no dot, no slash.
DATABASE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

_current_database: ContextVar[str | None] = ContextVar("current_database", default=None)


class DatabaseNameError(ValueError):
    """ The name is not acceptable as a tenant database. """


class DatabaseSwitchError(RuntimeError):
    """ Switching database while a transaction is open on the current one. """


# ------------------------------------------------------
# Current Database
# ------------------------------------------------------

def default_database() -> str:
    """ Name of the database used when none is active. """
    return settings.DATABASES[DEFAULT_DB_ALIAS]["NAME"]


def current_database() -> str:
    """ Name of the database the current unit of work runs on. """
    return _current_database.get() or default_database()


def validate_database_name(db_name: str) -> str:
    """ Check the name syntactically, and return it.

    The catalog of tenants is not looked up: the name comes from the proxy,
    which already resolved it, or from an operator. A static alias is refused,
    as it would otherwise be reachable as a tenant database.
    """
    if not isinstance(db_name, str) or not DATABASE_NAME_RE.match(db_name):
        raise DatabaseNameError(f"Invalid database name: {db_name!r}")
    if db_name in settings.DATABASES and db_name not in connections.tenant_aliases():
        raise DatabaseNameError(f"{db_name!r} is a static database alias, not a tenant database")
    return db_name


@contextlib.contextmanager
def use_database(db_name: str) -> t.Iterator[str]:
    """ Run the block on the given database.

    Blocks can be nested: leaving one restores the database of the enclosing
    block. Works in async code too, as `sync_to_async` copies the context into
    the thread running the ORM.

    Switching is refused while the current connection is in a transaction: the
    `atomic()` opened on `default` would be closed on another database.
    """
    validate_database_name(db_name)
    current = current_database()
    if db_name != current:
        connection = connections.get_initialized(current)
        if connection is not None and connection.in_atomic_block:
            raise DatabaseSwitchError(
                f"Cannot switch to database {db_name!r} inside a transaction on {current!r}"
            )
    token = _current_database.set(db_name)
    try:
        yield db_name
    finally:
        _current_database.reset(token)


def tenant_databases() -> list[str]:
    """ Names of the databases of the active tenants.

    Read from the catalog (`saas_base`) when the deployment has one, by raw
    SQL: its schema belongs to the proxy, no model maps it yet. Otherwise the
    single database of the settings. Not cached: a tenant added or deactivated
    is seen by the next call.
    """
    from core.db.routers import SAAS_DB_ALIAS

    if SAAS_DB_ALIAS not in settings.DATABASES:
        return [default_database()]
    with connections[SAAS_DB_ALIAS].cursor() as cursor:
        cursor.execute("SELECT db_name FROM tenant WHERE active ORDER BY db_name")
        names = [row[0] for row in cursor.fetchall()]
    valid = []
    for db_name in names:
        if DATABASE_NAME_RE.match(db_name or ""):
            valid.append(db_name)
        else:
            logger.warning("Skipped tenant with an invalid database name: %r", db_name)
    return valid


# ------------------------------------------------------
# Connection Handler
# ------------------------------------------------------

class TenantConnectionHandler(ConnectionHandler):
    """ `connections["default"]` is the connection of the current database.

    Only the lookup of `default` is redirected. The `default` entry of
    `settings.DATABASES` is never connected as such: it is the template of
    every database alias, and the fallback database is reached through its own
    alias like any other. Otherwise the same database would have two
    connections, and an `atomic()` on one would not cover the other.

    The pool of a database lives until it is closed, with its threads, even
    once its connections are gone. Pools unused for `DB_POOL_EVICT_AFTER`
    seconds are therefore closed; the next use creates the pool again.
    """

    # Seconds between two looks for pools to evict: `__getitem__` runs on every
    # query, the look must stay off that path most of the time.
    EVICTION_CHECK_INTERVAL = 60

    def __init__(self, settings=None):
        super().__init__(settings)
        self._init_tenancy()

    def _init_tenancy(self):
        self._lock = threading.RLock()
        self._tenant_aliases = set()
        self._last_used = {}
        self._last_eviction_check = time.monotonic()

    def __getitem__(self, alias):
        if alias == DEFAULT_DB_ALIAS:
            alias = current_database()
        if alias not in self.settings:
            self._add_database(alias)
        conn = super().__getitem__(alias)
        self._touch(alias)
        return conn

    def __iter__(self):
        """ Iterate on `default`, the other static aliases and the database aliases.

        The database `default` currently stands for is left out: it is already
        reached as `default`. Django's test framework relies on it, as it maps
        the `databases` of a test case (`{"default"}`) onto this iteration: the
        alias would otherwise be seen twice, once allowed and once forbidden.
        """
        current = current_database()
        with self._lock:
            aliases = list(self.settings)
        return iter([alias for alias in aliases if alias != current])

    def all(self, initialized_only=False):
        # `default` is initialized when the connection of the current database is.
        return [
            self[alias]
            for alias in self
            if not initialized_only or hasattr(self._connections, self._resolve(alias))
        ]

    # Database Aliases

    def tenant_aliases(self) -> set[str]:
        """ Aliases added for a database, as opposed to the configured ones. """
        with self._lock:
            return set(self._tenant_aliases)

    def get_initialized(self, alias):
        """ The connection of the alias in this thread, if it was created. """
        return getattr(self._connections, self._resolve(alias), None)

    def _resolve(self, alias):
        return current_database() if alias == DEFAULT_DB_ALIAS else alias

    def _add_database(self, db_name):
        from core.db.routers import SAAS_DB_ALIAS

        # A reserved alias left out of the settings (no catalog configured) is
        # not a tenant database either: same error as an unknown alias, as
        # before this handler existed.
        if not DATABASE_NAME_RE.match(db_name) or db_name in (DEFAULT_DB_ALIAS, SAAS_DB_ALIAS):
            raise self.exception_class(f"The connection '{db_name}' doesn't exist.")
        with self._lock:
            if db_name in self.settings:
                return
            # Copied after `configure_settings` filled in the defaults, so the
            # entry is complete. Deep: `OPTIONS` and `TEST` must not be shared,
            # the test runner rewrites the name of the test database in place.
            settings_dict = copy.deepcopy(self.settings[DEFAULT_DB_ALIAS])
            settings_dict["NAME"] = db_name
            # Named after its database in the logs of psycopg_pool, which
            # report the connection errors (rather than `pool-1`).
            if isinstance(settings_dict["OPTIONS"].get("pool"), dict):
                settings_dict["OPTIONS"]["pool"].setdefault("name", db_name)
            self.settings[db_name] = settings_dict
            self._tenant_aliases.add(db_name)

    # Pool Eviction

    def _touch(self, alias):
        now = time.monotonic()
        self._last_used[alias] = now
        if now - self._last_eviction_check >= self.EVICTION_CHECK_INTERVAL:
            self._last_eviction_check = now
            self.evict_idle_pools(now)

    def evict_idle_pools(self, now=None) -> list[str]:
        """ Close the pools unused for `DB_POOL_EVICT_AFTER` seconds. """
        from django.db.backends.postgresql.base import DatabaseWrapper

        now = time.monotonic() if now is None else now
        evict_after = float(env("DB_POOL_EVICT_AFTER", default="600"))
        evicted = []
        with self._lock:
            for alias, pool in list(DatabaseWrapper._connection_pools.items()):
                if now - self._last_used.get(alias, now) < evict_after:
                    continue
                stats = pool.get_stats()
                # A connection still borrowed belongs to a long transaction:
                # closing the pool would close it under its feet.
                if stats.get("pool_size", 0) - stats.get("pool_available", 0) > 0:
                    continue
                pool.close()
                DatabaseWrapper._connection_pools.pop(alias, None)
                evicted.append(alias)
        if evicted:
            logger.info("Closed idle connection pools: %s", ", ".join(evicted))
        return evicted


def install() -> None:
    """ Swap the class of `django.db.connections` for the tenant handler.

    The instance is kept, rather than replaced: modules hold it since their
    import (`from django.db import connections`), as does `django.db.connection`.
    Must run before any database access; nothing is connected at import time.
    """
    from django.db import connections as django_connections

    if isinstance(django_connections, TenantConnectionHandler):
        return
    django_connections.__class__ = TenantConnectionHandler
    # The class swap does not run `__init__` again.
    django_connections._init_tenancy()


install()

from django.db import connections  # noqa: E402  the instance installed above


# ------------------------------------------------------
# Cache
# ------------------------------------------------------

def make_cache_key(key, key_prefix, version):
    """ `KEY_FUNCTION` of the caches: the key is namespaced by the database.

    The same key set by two tenants names two entries, so a cached value of
    one is never served to another. Django's default is
    `f"{key_prefix}:{version}:{key}"`; the database comes after the prefix,
    which stays the namespace of the deployment.

    Not covered: `cache.clear()` empties the whole cache, every tenant alike.
    """
    return f"{key_prefix}:{current_database()}:{version}:{key}"


# ------------------------------------------------------
# Logging
# ------------------------------------------------------

class DatabaseNameFilter(logging.Filter):
    """ Add the current database as `db_name` to every log record. """

    def filter(self, record):
        try:
            record.db_name = current_database()
        except Exception:  # settings not configured yet
            record.db_name = None
        return True
