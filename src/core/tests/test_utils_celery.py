import json

from django.test import TestCase
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from core.utils.celery import ensure_periodic_task


class EnsurePeriodicTaskTestCase(TestCase):

    def test_create(self):
        periodic_task, created = ensure_periodic_task(
            "Test periodic task",
            "base.tasks.clear_sessions",
            crontab={"minute": "15", "hour": "3"},
            kwargs={"foo": 1},
        )

        self.assertTrue(created)
        self.assertEqual(periodic_task.task, "base.tasks.clear_sessions")
        self.assertEqual(json.loads(periodic_task.kwargs), {"foo": 1})
        self.assertTrue(periodic_task.enabled)
        self.assertEqual(periodic_task.crontab.minute, "15")
        self.assertEqual(periodic_task.crontab.hour, "3")
        self.assertEqual(periodic_task.crontab.day_of_week, "*")

    def test_existing_schedule_is_kept(self):
        """A schedule changed from the admin survives a later `populate`."""
        periodic_task, dummy = ensure_periodic_task(
            "Test periodic task",
            "base.tasks.clear_sessions",
            crontab={"minute": "15", "hour": "3"},
        )
        admin_schedule = CrontabSchedule.objects.create(minute="*/5")
        periodic_task.crontab = admin_schedule
        periodic_task.enabled = False
        periodic_task.save()

        periodic_task, created = ensure_periodic_task(
            "Test periodic task",
            "base.tasks.clear_sessions",
            crontab={"minute": "15", "hour": "3"},
        )

        self.assertFalse(created)
        periodic_task.refresh_from_db()
        self.assertEqual(periodic_task.crontab, admin_schedule)
        self.assertFalse(periodic_task.enabled)
        self.assertEqual(PeriodicTask.objects.filter(name="Test periodic task").count(), 1)

    def test_crontab_is_shared(self):
        ensure_periodic_task("Task A", "base.tasks.clear_sessions", crontab={"minute": "0", "hour": "2"})
        ensure_periodic_task("Task B", "oauth.tasks.clear_tokens", crontab={"minute": "0", "hour": "2"})

        self.assertEqual(CrontabSchedule.objects.filter(minute="0", hour="2").count(), 1)
