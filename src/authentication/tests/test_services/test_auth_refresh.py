from datetime import timedelta

from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from parameterized import parameterized

from authentication.models import RefreshToken
from authentication.services import AuthService, InvalidRefreshToken
from authentication.tokens import hash_secret
from core.testing import ServiceTestCaseMixin
from user.models import User

from authentication.tests.test_services.common_auth import PASSWORD, AuthServiceCommonMixin


@freeze_time("2024-11-18 11:12:13")
class AuthRefreshServiceTest(AuthServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `refresh`: rotate a pair. The token presented is spent, a successor of the
    same session is issued, and a replay revokes the whole session. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AuthService)
        self.first = async_to_sync(self.service.login)("frodon@lacomte.com", PASSWORD)

    # ------------------------------------------
    # Refresh
    # ------------------------------------------

    def test_refresh(self):
        issued = RefreshToken.objects.get()

        # The token locked, its revocation, the roles for the scopes, the new row.
        with self.assertNumQueries(6):
            second = async_to_sync(self.service.refresh)(self.first.refresh_token)

        self.assertNotEqual(second.refresh_token, self.first.refresh_token)
        self.assertEqual(RefreshToken.objects.count(), 2)
        self.assertIsNotNone(RefreshToken.objects.get(pk=issued.pk).revoked_at)
        successor = RefreshToken.objects.get(secret_hash=hash_secret(second.refresh_token))
        # Same chain, so a replay of either kills both.
        self.assertEqual((successor.revoked_at, successor.session_id), (None, issued.session_id))

    def test_refresh_reads_the_live_roles(self):
        # A right granted reaches the client within one access token lifetime,
        # without anyone being signed out.
        self.role.permissions = ["totem.user.read", "totem.contact.read", "totem.account.read"]
        self.role.save(update_fields=["permissions"])

        second = async_to_sync(self.service.refresh)(self.first.refresh_token)

        self.assertEqual(second.scope, "totem.account.read totem.contact.read totem.user.read")

    @parameterized.expand(
        [
            ("an unknown token", "never-issued", 0, 1),
            # Revoked, then reported: the revocation survives the failure.
            ("an expired token", None, 14 * 24 * 3600 + 1, 0),
        ]
    )
    def test_refresh_invalid(self, label, secret, seconds_later, active_left):
        with freeze_time(timezone.now() + timedelta(seconds=seconds_later)):
            with self.assertRaises(InvalidRefreshToken):
                async_to_sync(self.service.refresh)(secret or self.first.refresh_token)

        self.assertEqual(RefreshToken.objects.active().count(), active_left)

    def test_refresh_of_a_deactivated_user(self):
        # Takes effect at once: every token of the user is revoked, those of
        # the other session too.
        other_session = async_to_sync(self.service.login)("frodon@lacomte.com", PASSWORD)
        User.objects.filter(pk=self.user_frodon.pk).update(is_active=False)

        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(self.first.refresh_token)

        self.assertFalse(RefreshToken.objects.active().exists())
        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(other_session.refresh_token)

    def test_refresh_replayed(self):
        # The legitimate client repeating a lost request, or a thief: nothing can
        # tell them apart, so the whole chain goes (RFC 9700, 4.14.2).
        second = async_to_sync(self.service.refresh)(self.first.refresh_token)
        other_session = async_to_sync(self.service.login)("frodon@lacomte.com", PASSWORD)

        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(self.first.refresh_token)

        # Written in the transaction the rejection is decided in, and kept: a
        # raise from inside would have rolled it back.
        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(second.refresh_token)
        # Another session is another chain: it still works.
        self.assertTrue(async_to_sync(self.service.refresh)(other_session.refresh_token))
