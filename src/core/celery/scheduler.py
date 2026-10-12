"""One beat for the periodic tasks of every tenant.

Each tenant keeps its schedule in its own database (`django_celery_beat`
tables), editable from its admin. Beat runs one native `DatabaseScheduler` per
tenant database, each always working inside that database: it reads its
schedule there, records the runs there, and sends the due tasks from there, so
that each message carries the database of its tenant (see `core.celery`).

Rejected alternative: a single schedule in the catalog, fanned out to every
tenant at run time. It would take the schedule out of the hands of the
tenants, and `django_celery_beat` has no notion of a tenant to fan out to.
"""
import contextlib
import logging
import time

from celery.beat import Scheduler
from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections
from django_celery_beat.schedulers import DEFAULT_MAX_INTERVAL, DatabaseScheduler

from core.db.tenancy import tenant_databases, use_database

logger = logging.getLogger(__name__)


class TenantScheduler(DatabaseScheduler):
    """ The `DatabaseScheduler` of one tenant database.

    Every entry point that may reach the database selects it first, `sync()`
    included: it is also registered to run at exit (`Finalize`), outside of any
    tenant, where it would otherwise save the runs of this tenant into the
    default database.
    """

    def __init__(self, *args, db_name, parent, **kwargs):
        self.db_name = db_name
        self.parent = parent
        with self.in_database():
            super().__init__(*args, **kwargs)

    @property
    def producer(self):
        # One broker connection for the whole beat, not one per tenant.
        return self.parent.producer

    @contextlib.contextmanager
    def in_database(self):
        """ Select the database of this tenant, and release it afterwards.

        Beat looks at each tenant every few minutes only: between two looks,
        the connection and the pool would just sit idle, one per tenant, with
        the threads of the pool. Closed here, as the Celery worker does after
        each task.
        """
        with use_database(self.db_name):
            try:
                yield
            finally:
                connection = connections[DEFAULT_DB_ALIAS]
                connection.close()
                connection.close_pool()

    def tick(self, *args, **kwargs):
        with self.in_database():
            return super().tick(*args, **kwargs)

    def sync(self):
        with self.in_database():
            return super().sync()

    def close(self):
        with self.in_database():
            return super().close()


class TenantDatabaseScheduler(Scheduler):
    """ Runs the `TenantScheduler` of each active tenant, in turn.

    The list of tenants (`tenant_databases()`) is read again every
    `BEAT_TENANT_REFRESH` seconds: a new tenant gets its scheduler, a removed
    or deactivated one loses it. A tenant whose schedule cannot be read (its
    database is unreachable, or not migrated yet) is logged and retried at the
    next refresh, without stopping the others.
    """

    Scheduler = TenantScheduler

    # When `beat_max_loop_interval` is not set; as `DatabaseScheduler`.
    max_interval = DEFAULT_MAX_INTERVAL

    def __init__(self, *args, **kwargs):
        self.schedulers = {}
        self._last_refresh = None
        super().__init__(*args, **kwargs)

    def setup_schedule(self):
        self.refresh_databases()

    # Tenants

    def refresh_databases(self):
        self._last_refresh = time.monotonic()
        try:
            db_names = tenant_databases()
        except Exception:
            logger.exception("beat: could not read the list of tenants, keeping the current one")
            return

        for db_name in set(self.schedulers) - set(db_names):
            self._remove_scheduler(db_name)
        for db_name in db_names:
            if db_name not in self.schedulers:
                self._add_scheduler(db_name)

    def _add_scheduler(self, db_name):
        try:
            self.schedulers[db_name] = self.Scheduler(
                app=self.app,
                max_interval=self.max_interval,
                Producer=self.Producer,
                db_name=db_name,
                parent=self,
            )
        except Exception:
            logger.exception("beat: could not load the schedule of %s", db_name)
        else:
            logger.info("beat: scheduling the periodic tasks of %s", db_name)

    def _remove_scheduler(self, db_name):
        scheduler = self.schedulers.pop(db_name)
        try:
            scheduler.close()
        except Exception:
            logger.exception("beat: could not save the schedule of %s", db_name)
        # Already synced: nothing left for the exit hook to do.
        scheduler._finalize.cancel()
        logger.info("beat: stopped scheduling the periodic tasks of %s", db_name)

    def _refresh_due(self):
        return time.monotonic() - self._last_refresh >= settings.BEAT_TENANT_REFRESH

    # Scheduler

    def tick(self, *args, **kwargs):
        """ Tick each tenant once: at most one task sent per tenant.

        Returns the shortest delay asked by a tenant: 0 when one of them sent a
        task, so that beat ticks again right away.
        """
        if self._refresh_due():
            self.refresh_databases()
        intervals = []
        for db_name, scheduler in list(self.schedulers.items()):
            try:
                intervals.append(scheduler.tick())
            except Exception:
                logger.exception("beat: tick failed for %s", db_name)
        return min(intervals, default=self.max_interval)

    def sync(self):
        for db_name, scheduler in list(self.schedulers.items()):
            try:
                scheduler.sync()
            except Exception:
                logger.exception("beat: could not save the schedule of %s", db_name)

    def close(self):
        self.sync()

    @property
    def info(self):
        return f"    . tenants -> {len(self.schedulers)} database(s), refreshed every {settings.BEAT_TENANT_REFRESH}s"
