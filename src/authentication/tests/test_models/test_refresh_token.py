from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from authentication.models import RefreshToken
from authentication.tokens import hash_secret
from user import choices as user_choices
from user.models import User


@freeze_time("2024-11-18 11:12:13")
class TestRefreshTokenQuerySet(TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create(
            username="frodon@lacomte.com",
            email="frodon@lacomte.com",
            user_type=user_choices.UserType.INTERNAL,
        )
        cls.other_user = User.objects.create(
            username="gollum@precious.com",
            email="gollum@precious.com",
            user_type=user_choices.UserType.PORTAL,
        )

    # ---------------------------------------------------------
    # issue
    # ---------------------------------------------------------

    def test_issue_stores_only_the_hash(self):
        token, secret = RefreshToken.objects.issue(self.user)

        self.assertEqual(token.secret_hash, hash_secret(secret))
        self.assertNotEqual(token.secret_hash, secret)
        # The clear secret is nowhere in the row.
        self.assertNotIn(secret, str(RefreshToken.objects.values().get(pk=token.pk)))

    def test_issue_sets_the_expiry_from_the_settings(self):
        token, dummy = RefreshToken.objects.issue(self.user)
        self.assertEqual(token.expires_at, timezone.now() + timedelta(days=14))

    def test_issue_starts_a_session_when_none_is_given(self):
        first, dummy = RefreshToken.objects.issue(self.user)
        second, dummy = RefreshToken.objects.issue(self.user)
        self.assertNotEqual(first.session_id, second.session_id)

    def test_issue_continues_a_given_session(self):
        first, dummy = RefreshToken.objects.issue(self.user)
        second, dummy = RefreshToken.objects.issue(self.user, session_id=first.session_id)
        self.assertEqual(second.session_id, first.session_id)

    # ---------------------------------------------------------
    # active / revoke
    # ---------------------------------------------------------

    def test_active_excludes_expired_and_revoked(self):
        live, dummy = RefreshToken.objects.issue(self.user)
        expired, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now())
        revoked, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=revoked.pk).revoke()

        self.assertEqual([t.pk for t in RefreshToken.objects.active()], [live.pk])

    def test_revoke_keeps_the_first_timestamp(self):
        # The timestamp is the evidence a replay is recognised by: a second
        # revocation must not move it.
        token, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=token.pk).revoke()
        first = RefreshToken.objects.get(pk=token.pk).revoked_at

        with freeze_time("2024-11-18 12:00:00"):
            self.assertEqual(RefreshToken.objects.filter(pk=token.pk).revoke(), 0)
        self.assertEqual(RefreshToken.objects.get(pk=token.pk).revoked_at, first)

    def test_revoke_session_kills_the_whole_chain(self):
        first, dummy = RefreshToken.objects.issue(self.user)
        second, dummy = RefreshToken.objects.issue(self.user, session_id=first.session_id)
        third, dummy = RefreshToken.objects.issue(self.user, session_id=first.session_id)
        other_session, dummy = RefreshToken.objects.issue(self.user)

        self.assertEqual(RefreshToken.objects.revoke_session(first.session_id), 3)
        self.assertEqual(
            [t.pk for t in RefreshToken.objects.active()], [other_session.pk]
        )

    def test_revoke_for_users_leaves_the_others_alone(self):
        mine, dummy = RefreshToken.objects.issue(self.user)
        theirs, dummy = RefreshToken.objects.issue(self.other_user)

        RefreshToken.objects.revoke_for_users(User.objects.filter(pk=self.user.pk))

        self.assertIsNotNone(RefreshToken.objects.get(pk=mine.pk).revoked_at)
        self.assertIsNone(RefreshToken.objects.get(pk=theirs.pk).revoked_at)

    # ---------------------------------------------------------
    # purge_expired
    # ---------------------------------------------------------

    def test_purge_expired_keeps_revoked_but_unexpired_rows(self):
        # A revoked token is kept until its original expiry: that window is
        # exactly when replaying it must still be detected.
        revoked, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=revoked.pk).revoke()
        expired, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=expired.pk).update(expires_at=timezone.now())

        self.assertEqual(RefreshToken.objects.purge_expired(), 1)
        self.assertEqual([t.pk for t in RefreshToken.objects.all()], [revoked.pk])

    def test_purge_expired_is_idempotent(self):
        token, dummy = RefreshToken.objects.issue(self.user)
        RefreshToken.objects.filter(pk=token.pk).update(expires_at=timezone.now())

        self.assertEqual(RefreshToken.objects.purge_expired(), 1)
        self.assertEqual(RefreshToken.objects.purge_expired(), 0)

    # ---------------------------------------------------------
    # Model
    # ---------------------------------------------------------

    def test_is_usable(self):
        token, dummy = RefreshToken.objects.issue(self.user)
        self.assertTrue(token.is_usable())

        token.revoked_at = timezone.now()
        self.assertFalse(token.is_usable())

    def test_deleting_the_user_deletes_the_tokens(self):
        RefreshToken.objects.issue(self.user)
        self.user.delete()
        self.assertFalse(RefreshToken.objects.exists())
