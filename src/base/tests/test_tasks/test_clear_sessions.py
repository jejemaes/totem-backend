import datetime

from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone

from base.tasks import clear_sessions


class ClearSessionsTestCase(TestCase):

    def test_clear_sessions(self):
        Session.objects.create(
            session_key="expired",
            session_data="",
            expire_date=timezone.now() - datetime.timedelta(days=1),
        )
        Session.objects.create(
            session_key="valid",
            session_data="",
            expire_date=timezone.now() + datetime.timedelta(days=1),
        )

        clear_sessions()

        self.assertEqual(list(Session.objects.values_list("session_key", flat=True)), ["valid"])
