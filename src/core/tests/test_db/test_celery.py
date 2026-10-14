import datetime
import io
from unittest import mock

from celery import Celery, shared_task
from celery.app.task import Task
from celery.signals import before_task_publish
from django.core.management import call_command
from django.db import connections
from django.db.backends.postgresql.base import DatabaseWrapper
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from kombu import Connection

from core.celery import DB_NAME_HEADER, TenantTask, add_db_name_header
from core.celery.scheduler import TenantDatabaseScheduler, TenantScheduler
from core.db.tenancy import current_database, default_database, use_database
from core.testing import TenantDatabaseTestMixin
from totem.celery import app as celery_app


@shared_task
def database_of_task():
    return current_database()


class PublishTestCase(SimpleTestCase):

    def test_header_is_the_current_database(self):
        headers = {}
        add_db_name_header(headers=headers)
        self.assertEqual(headers[DB_NAME_HEADER], default_database())
        with use_database("tenant_a"):
            headers = {}
            add_db_name_header(headers=headers)
        self.assertEqual(headers[DB_NAME_HEADER], "tenant_a")

    def test_explicit_header_kept(self):
        headers = {DB_NAME_HEADER: "tenant_b"}
        with use_database("tenant_a"):
            add_db_name_header(headers=headers)
        self.assertEqual(headers[DB_NAME_HEADER], "tenant_b")

    def test_published_message_carries_the_database(self):
        published = []

        def capture(headers=None, **kwargs):
            published.append(headers.get(DB_NAME_HEADER))

        before_task_publish.connect(capture)
        self.addCleanup(before_task_publish.disconnect, capture)
        # An in-memory broker: the message is really built and published.
        with Connection("memory://") as connection, use_database("tenant_a"):
            database_of_task.apply_async(connection=connection)

        self.assertEqual(published, ["tenant_a"])


class TenantTaskTestCase(SimpleTestCase):

    def test_default_task_class(self):
        self.assertIsInstance(database_of_task, TenantTask)
        self.assertTrue(issubclass(celery_app.Task, TenantTask))

    def test_runs_on_the_database_of_the_message(self):
        # As a worker does: the message headers are on the request.
        database_of_task.push_request(**{DB_NAME_HEADER: "tenant_a"})
        try:
            self.assertEqual(database_of_task(), "tenant_a")
        finally:
            database_of_task.pop_request()
        self.assertEqual(current_database(), default_database())

    def test_apply_with_headers(self):
        result = database_of_task.apply(headers={DB_NAME_HEADER: "tenant_a"})
        self.assertEqual(result.get(), "tenant_a")

    def test_direct_call_stays_on_the_caller_database(self):
        with use_database("tenant_a"):
            self.assertEqual(database_of_task(), "tenant_a")


class TenantSchedulerTestCase(TenantDatabaseTestMixin, TransactionTestCase):
    """ One beat, a schedule in each of two databases. """

    def setUp(self):
        super().setUp()
        self.sent = []
        self.make_due_task("job")
        with use_database(self.tenant_db):
            self.make_due_task("job")

        databases = mock.patch(
            "core.celery.scheduler.tenant_databases",
            return_value=[default_database(), self.tenant_db],
        )
        self.tenant_databases = databases.start()
        self.addCleanup(databases.stop)
        # No broker: record each sent task with the database it was sent from.
        # Beat sends by name a task not imported in its process (`send_task`).
        for patcher in [
            mock.patch.object(TenantDatabaseScheduler, "producer", None),
            mock.patch.object(Task, "apply_async", autospec=True, side_effect=self.record_task),
            mock.patch.object(Celery, "send_task", autospec=True, side_effect=self.record_name),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def record_task(self, task, *args, **kwargs):
        self.sent.append((task.name, current_database()))

    def record_name(self, app, name, *args, **kwargs):
        self.sent.append((name, current_database()))

    def make_due_task(self, name):
        every_hour, dummy = IntervalSchedule.objects.get_or_create(every=1, period=IntervalSchedule.HOURS)
        return PeriodicTask.objects.create(
            name=name,
            task="base.tasks.clear_sessions",
            interval=every_hour,
            last_run_at=timezone.now() - datetime.timedelta(hours=2),
        )

    def make_scheduler(self):
        scheduler = TenantDatabaseScheduler(app=celery_app, lazy=False)
        self.addCleanup(self.close, scheduler)
        return scheduler

    def close(self, scheduler):
        for sub in scheduler.schedulers.values():
            sub._finalize.cancel()

    def run_counts(self):
        counts = {default_database(): PeriodicTask.objects.get(name="job").total_run_count}
        with use_database(self.tenant_db):
            counts[self.tenant_db] = PeriodicTask.objects.get(name="job").total_run_count
        return counts

    def test_each_database_sends_its_tasks(self):
        scheduler = self.make_scheduler()
        self.assertEqual(set(scheduler.schedulers), {default_database(), self.tenant_db})

        self.assertEqual(scheduler.tick(), 0)  # sent: tick again right away

        self.assertCountEqual(
            self.sent,
            [("base.tasks.clear_sessions", default_database()), ("base.tasks.clear_sessions", self.tenant_db)],
        )
        self.assertEqual(current_database(), default_database())

    def test_connections_released_after_each_look(self):
        """ Nothing idle between two ticks: no connection, no pool. """
        scheduler = self.make_scheduler()
        scheduler.tick()
        self.assertNotIn(self.tenant_db, DatabaseWrapper._connection_pools)
        self.assertIsNone(connections.get_initialized(self.tenant_db).connection)

    def test_runs_recorded_in_their_own_database(self):
        scheduler = self.make_scheduler()
        scheduler.tick()
        scheduler.close()

        self.assertEqual(self.run_counts(), {default_database(): 1, self.tenant_db: 1})

    def test_sync_outside_of_any_tenant(self):
        """ The exit hook syncs with no database selected. """
        scheduler = self.make_scheduler()
        scheduler.tick()
        for sub in scheduler.schedulers.values():
            sub.sync()

        self.assertEqual(self.run_counts(), {default_database(): 1, self.tenant_db: 1})

    def test_refresh_follows_the_tenants(self):
        scheduler = self.make_scheduler()
        self.tenant_databases.return_value = [self.tenant_db]
        scheduler.refresh_databases()
        self.assertEqual(set(scheduler.schedulers), {self.tenant_db})

        scheduler.tick()
        self.assertEqual(self.sent, [("base.tasks.clear_sessions", self.tenant_db)])

    def test_broken_tenant_does_not_stop_the_others(self):
        original = TenantScheduler.__init__

        def init(sub, *args, db_name, **kwargs):
            if db_name == self.tenant_db:
                raise RuntimeError("unreachable database")
            original(sub, *args, db_name=db_name, **kwargs)

        with mock.patch.object(TenantScheduler, "__init__", init), self.assertLogs("core.celery.scheduler", "ERROR"):
            scheduler = self.make_scheduler()
        self.assertEqual(set(scheduler.schedulers), {default_database()})

        scheduler.tick()
        self.assertEqual(self.sent, [("base.tasks.clear_sessions", default_database())])

        # Retried on the next refresh.
        scheduler.refresh_databases()
        self.assertEqual(set(scheduler.schedulers), {default_database(), self.tenant_db})


class TenantMigrateAllTestCase(TenantDatabaseTestMixin, TransactionTestCase):

    def test_all_migrates_every_tenant(self):
        out = io.StringIO()
        with mock.patch(
            "saas.management.commands.tenant_migrate.tenant_databases",
            return_value=[default_database(), self.tenant_db],
        ):
            call_command("tenant_migrate", "--all", "--remove-stale-contenttypes", stdout=out)
        self.assertIn(f"Database {default_database()}:", out.getvalue())
        self.assertIn(f"Database {self.tenant_db}:", out.getvalue())

    def test_name_or_all(self):
        with self.assertRaises(CommandError):
            call_command("tenant_migrate", verbosity=0)
        with self.assertRaises(CommandError):
            call_command("tenant_migrate", self.tenant_db, "--all", verbosity=0)
