from datetime import timedelta

from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from authentication.models import RefreshToken
from authentication.services import AuthService, InvalidCredentials, InvalidRefreshToken
from authentication.tokens import decode_access_token, hash_secret
from core.services import Environment
from user import choices as user_choices
from user.models import User, UserRole

PASSWORD = "a-perfectly-fine-password"


@freeze_time("2024-11-18 11:12:13")
class TestAuthService(TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.role = UserRole.objects.create(
            id="TEST_BASEUSER",
            name="Role Test (Base)",
            permissions=["totem.user.read", "totem.contact.read"],
        )
        cls.user = User.objects.create(
            username="frodon@lacomte.com",
            email="frodon@lacomte.com",
            user_type=user_choices.UserType.INTERNAL,
        )
        cls.user.set_password(PASSWORD)
        cls.user.save(update_fields=["password"])
        cls.user.roles.set([cls.role])

    def setUp(self):
        super().setUp()
        # `Environment(None)`: the caller of a login is anonymous by construction,
        # which is the whole reason `AuthService` is bound to no model.
        self.service = Environment(None).get(AuthService)

    # ---------------------------------------------------------
    # login
    # ---------------------------------------------------------

    def test_login_returns_a_pair(self):
        pair = async_to_sync(self.service.login)(self.user.username, PASSWORD)

        self.assertEqual(pair.token_type, "Bearer")
        self.assertEqual(pair.expires_in, 15 * 60)
        self.assertEqual(pair.scope, "totem.contact.read totem.user.read")

        claims = decode_access_token(pair.access_token)
        self.assertEqual(claims["sub"], str(self.user.pk))
        self.assertEqual(claims["scope"], "totem.contact.read totem.user.read")

    def test_login_stores_only_the_hash_of_the_refresh_token(self):
        pair = async_to_sync(self.service.login)(self.user.username, PASSWORD)

        token = RefreshToken.objects.get()
        self.assertEqual(token.user_id, self.user.pk)
        self.assertEqual(token.secret_hash, hash_secret(pair.refresh_token))
        self.assertNotEqual(token.secret_hash, pair.refresh_token)

    def test_login_updates_last_login(self):
        # Nothing else would: `update_last_login` is wired to `user_logged_in`,
        # which only `django.contrib.auth.login()` emits, and a token flow never
        # calls it.
        self.assertIsNone(self.user.last_login)
        async_to_sync(self.service.login)(self.user.username, PASSWORD)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_login, timezone.now())

    def test_login_with_no_role_grants_no_scope(self):
        self.user.roles.clear()
        pair = async_to_sync(self.service.login)(self.user.username, PASSWORD)

        self.assertEqual(pair.scope, "")
        self.assertEqual(decode_access_token(pair.access_token)["scope"], "")

    def test_every_failure_is_the_same_failure(self):
        inactive = User.objects.create(
            username="sauron@mordor.com",
            email="sauron@mordor.com",
            user_type=user_choices.UserType.INTERNAL,
            is_active=False,
        )
        inactive.set_password(PASSWORD)
        inactive.save(update_fields=["password"])

        cases = {
            "wrong password": (self.user.username, "not-the-password"),
            "unknown login": ("nobody@nowhere.com", PASSWORD),
            "inactive account": (inactive.username, PASSWORD),
            # `User.objects.create()` leaves an unusable hash, which is what every
            # user of the fixtures has.
            "unusable password": ("gandalf@istari.com", PASSWORD),
        }
        User.objects.create(
            username="gandalf@istari.com",
            email="gandalf@istari.com",
            user_type=user_choices.UserType.INTERNAL,
        )

        for label, (username, password) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(InvalidCredentials):
                    async_to_sync(self.service.login)(username, password)

        self.assertFalse(RefreshToken.objects.exists())

    # ---------------------------------------------------------
    # refresh
    # ---------------------------------------------------------

    def test_refresh_rotates_the_pair(self):
        first = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        issued = RefreshToken.objects.get()

        second = async_to_sync(self.service.refresh)(first.refresh_token)

        self.assertNotEqual(second.refresh_token, first.refresh_token)
        self.assertEqual(RefreshToken.objects.count(), 2)

        issued.refresh_from_db()
        self.assertIsNotNone(issued.revoked_at)

        successor = RefreshToken.objects.get(secret_hash=hash_secret(second.refresh_token))
        self.assertIsNone(successor.revoked_at)
        # Same chain, so a replay of either kills both.
        self.assertEqual(successor.session_id, issued.session_id)

    def test_refresh_recomputes_the_scopes_from_the_live_roles(self):
        first = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        self.role.permissions = ["totem.user.read", "totem.contact.read", "totem.account.read"]
        self.role.save(update_fields=["permissions"])

        second = async_to_sync(self.service.refresh)(first.refresh_token)

        self.assertEqual(
            second.scope, "totem.account.read totem.contact.read totem.user.read"
        )

    def test_refresh_of_an_unknown_token(self):
        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)("never-issued")

    def test_replay_revokes_the_whole_session(self):
        first = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        second = async_to_sync(self.service.refresh)(first.refresh_token)

        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(first.refresh_token)

        # The revocation must survive the failure: it is written in the same
        # transaction the rejection is decided in, so a raise from inside would
        # roll it back and leave a stolen chain live.
        self.assertFalse(RefreshToken.objects.active().exists())
        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(second.refresh_token)

    def test_replay_leaves_other_sessions_alone(self):
        first = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        other_session = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        async_to_sync(self.service.refresh)(first.refresh_token)

        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(first.refresh_token)

        # The other session is a different chain, so it still works.
        self.assertTrue(async_to_sync(self.service.refresh)(other_session.refresh_token))

    def test_refresh_of_an_expired_token(self):
        pair = async_to_sync(self.service.login)(self.user.username, PASSWORD)

        with freeze_time(timezone.now() + timedelta(days=14, seconds=1)):
            with self.assertRaises(InvalidRefreshToken):
                async_to_sync(self.service.refresh)(pair.refresh_token)

        self.assertIsNotNone(RefreshToken.objects.get().revoked_at)

    def test_refresh_after_the_user_was_deactivated(self):
        pair = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(pair.refresh_token)

        self.assertFalse(RefreshToken.objects.active().exists())

    # ---------------------------------------------------------
    # revoke
    # ---------------------------------------------------------

    def test_revoke_ends_the_session(self):
        pair = async_to_sync(self.service.login)(self.user.username, PASSWORD)

        async_to_sync(self.service.revoke)(pair.refresh_token)

        self.assertFalse(RefreshToken.objects.active().exists())
        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(pair.refresh_token)

    def test_revoke_of_an_unknown_token_says_nothing(self):
        # No exception: the endpoint answers the same either way, so a caller
        # cannot probe which secrets are live.
        self.assertIsNone(async_to_sync(self.service.revoke)("never-issued"))

    def test_revoke_kills_the_chain_not_just_the_token(self):
        first = async_to_sync(self.service.login)(self.user.username, PASSWORD)
        second = async_to_sync(self.service.refresh)(first.refresh_token)

        async_to_sync(self.service.revoke)(second.refresh_token)

        self.assertFalse(RefreshToken.objects.active().exists())
