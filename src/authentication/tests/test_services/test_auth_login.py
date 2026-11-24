from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from parameterized import parameterized

from authentication.models import RefreshToken
from authentication.services import AuthService, InvalidCredentials
from authentication.tokens import decode_access_token, hash_secret
from core.testing import ServiceTestCaseMixin
from user.models import User

from authentication.tests.test_services.common_auth import PASSWORD, AuthServiceCommonMixin


@freeze_time("2024-11-18 11:12:13")
class AuthLoginServiceTest(AuthServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `login`: credentials for a first token pair. The caller is anonymous by
    construction -- it is proving who it is -- which is why `AuthService` is
    bound to no model. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AuthService)

    # ------------------------------------------
    # Login
    # ------------------------------------------

    @parameterized.expand(
        [
            ("with a role", ["totem.user.read", "totem.contact.read"], "totem.contact.read totem.user.read"),
            ("with a role granting nothing", [], ""),
        ]
    )
    def test_login(self, label, permissions, scope):
        self.role.permissions = permissions
        self.role.save(update_fields=["permissions"])

        # The user, the transaction, `last_login`, the roles for the scopes,
        # the refresh row.
        with self.assertNumQueries(6):
            pair = async_to_sync(self.service.login)("frodon@lacomte.com", PASSWORD)

        self.assertEqual((pair.token_type, pair.expires_in, pair.scope), ("Bearer", 15 * 60, scope))
        claims = decode_access_token(pair.access_token)
        self.assertEqual((claims["sub"], claims["scope"]), (str(self.user_frodon.pk), scope))
        # Only the hash of the refresh token is stored.
        token = RefreshToken.objects.get()
        self.assertEqual((str(token.user_id), token.secret_hash), (str(self.user_frodon.pk), hash_secret(pair.refresh_token)))
        # Nothing else would write it: `update_last_login` is wired to
        # `user_logged_in`, which only `django.contrib.auth.login()` emits.
        self.assertEqual(User.objects.get(pk=self.user_frodon.pk).last_login, timezone.now())

    @parameterized.expand(
        [
            # Every failure is the same failure: nothing tells them apart.
            ("a wrong password", "frodon@lacomte.com", "not-the-password"),
            ("an unknown login", "sauron@mordor.com", PASSWORD),
            ("an inactive account", "gollum@precious.com", PASSWORD),
            # `User.objects.create()` leaves an unusable hash.
            ("an unusable password", "sam@lacomte.com", PASSWORD),
        ]
    )
    def test_login_invalid(self, label, username, password):
        with self.assertRaises(InvalidCredentials):
            async_to_sync(self.service.login)(username, password)

        self.assertFalse(RefreshToken.objects.exists())
        self.assertIsNone(User.objects.get(pk=self.user_frodon.pk).last_login)
