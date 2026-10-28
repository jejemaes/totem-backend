import datetime

from django.test import TestCase
from django.utils import timezone

from authentication.models import RefreshToken
from authentication.tasks import clear_tokens
from user.models import User


class ClearTokensTestCase(TestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create(
            username="token-owner", email="token-owner@example.com"
        )

    def test_clear_tokens(self):
        expired, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - datetime.timedelta(days=1)
        )
        valid, dummy = RefreshToken.objects.issue(self.user)

        clear_tokens()

        self.assertFalse(RefreshToken.objects.filter(pk=expired.pk).exists())
        self.assertTrue(RefreshToken.objects.filter(pk=valid.pk).exists())

    def test_a_revoked_but_unexpired_token_is_kept(self):
        # The window in which replaying it still has to be detected.
        revoked, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=revoked.pk).revoke()

        clear_tokens()

        self.assertTrue(RefreshToken.objects.filter(pk=revoked.pk).exists())

    def test_clear_tokens_is_idempotent(self):
        expired, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now())

        clear_tokens()
        clear_tokens()

        self.assertFalse(RefreshToken.objects.exists())
