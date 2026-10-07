import datetime

from django.test import TestCase
from django.utils import timezone

from oauth.models import AccessToken
from oauth.tasks import clear_tokens
from user.models import User


class ClearTokensTestCase(TestCase):

    def test_clear_tokens(self):
        user = User.objects.create(username="token-owner", email="token-owner@example.com")
        expired = AccessToken.objects.create(
            user=user,
            token="expired-token",
            expires=timezone.now() - datetime.timedelta(days=1),
        )
        valid = AccessToken.objects.create(
            user=user,
            token="valid-token",
            expires=timezone.now() + datetime.timedelta(days=1),
        )

        clear_tokens()

        self.assertFalse(AccessToken.objects.filter(pk=expired.pk).exists())
        self.assertTrue(AccessToken.objects.filter(pk=valid.pk).exists())
