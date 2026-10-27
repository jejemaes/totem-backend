from django.conf import settings
from django.db import models
from django.utils import timezone

from authentication.tokens import generate_secret, hash_secret
from core.orm.fields import ULIDField, generate_ulid


class RefreshTokenQuerySet(models.QuerySet):

    def issue(self, user, *, session_id=None, now=None):
        """ Mint a refresh secret, store only its hash, and return the clear
        text once: `(instance, secret)`.

        The hash is derived here rather than in `AuthService` because this is the
        invariant that has to hold on *every* write path, including whichever one
        comes next -- the same reason `MediaQuerySet.bulk_create` derives the
        checksum of a media instead of its service doing it.

        `session_id` chains a rotation: a successor carries the id of its
        predecessor, so replaying any token of the chain can revoke the whole
        chain in one indexed UPDATE. A self-FK `rotated_to` would describe the
        chain more precisely and buy nothing -- replay detection only ever needs
        to kill it.
        """
        now = now or timezone.now()
        secret = generate_secret()
        instance = self.create(
            user=user,
            secret_hash=hash_secret(secret),
            session_id=session_id or generate_ulid(),
            expires_at=now + settings.JWT_REFRESH_TOKEN_LIFETIME,
        )
        return instance, secret

    def active(self, now=None):
        """ The tokens that may still be exchanged. """
        now = now or timezone.now()
        return self.filter(revoked_at__isnull=True, expires_at__gt=now)

    def revoke(self, now=None) -> int:
        """ Revoke every token of this queryset, and return how many were still
        live.

        A token already revoked keeps its first `revoked_at`: that timestamp is
        what makes a replay recognisable afterwards, so overwriting it would
        erase the evidence the rotation relies on.
        """
        now = now or timezone.now()
        return self.filter(revoked_at__isnull=True).update(revoked_at=now)

    def revoke_session(self, session_id, now=None) -> int:
        """ Revoke a whole rotation chain, which is the answer to a replay. """
        return self.filter(session_id=session_id).revoke(now=now)

    def revoke_for_users(self, user_qs, now=None) -> int:
        """ Sign the given users out everywhere.

        Deliberately not wired to `user_change_rights`: a right taken away
        propagates on its own at the next rotation, since the scopes are
        recomputed from the live roles, so revoking there would sign everyone out
        for no gain in exposure. This is the hook for what does need it -- a
        password change, an explicit "sign out everywhere".
        """
        return self.filter(user__in=user_qs).revoke(now=now)

    def purge_expired(self, now=None) -> int:
        """ Delete what can no longer be exchanged, and return how many rows went.

        Expiry alone, not revocation: a revoked token is kept until its original
        expiry, because that is exactly the window in which replaying it must
        still be detected. Idempotent, as the periodic task may be redelivered
        (`CELERY_TASK_ACKS_LATE`).
        """
        now = now or timezone.now()
        deleted, dummy = self.filter(expires_at__lte=now).delete()
        return deleted


class RefreshToken(models.Model):
    """ A refresh token of one user session, as stored.

    An opaque random string rather than a JWT: the row is already the source of
    truth, so signing it would add nothing, and it makes "present a refresh token
    as an access token" structurally impossible -- `jwt.decode` cannot parse it
    at all.

    Deliberately no `scope` column: the scopes of the next access token are
    recomputed from the live roles at every rotation. That is what bounds how
    stale a right can be to the lifetime of a single access token, and what makes
    revoking tokens on a rights change unnecessary.
    """

    id = ULIDField("ID", primary_key=True)
    user = models.ForeignKey(
        "user.User",
        verbose_name="User",
        related_name="refresh_tokens",
        null=False,
        on_delete=models.CASCADE,
        help_text="The user this token authenticates when it is exchanged.",
    )
    secret_hash = models.CharField(
        "Secret Hash",
        max_length=64,
        null=False,
        blank=False,
        # The unique constraint is also the index the exchange looks the token up
        # by, so no separate `db_index`.
        unique=True,
        help_text=(
            "SHA-256 of the secret, hex. The secret itself is returned once, when the "
            "token is issued, and is never stored."
        ),
    )
    session_id = ULIDField(
        "Session",
        db_index=True,
        help_text=(
            "Shared by every token of one rotation chain: replaying any of them revokes "
            "them all."
        ),
    )
    expires_at = models.DateTimeField(
        "Expiration",
        null=False,
        help_text="After this, the token can no longer be exchanged, and is purged.",
    )
    created_at = models.DateTimeField("Created on", auto_now_add=True)
    revoked_at = models.DateTimeField(
        "Revoked on",
        null=True,
        blank=True,
        help_text=(
            "Set when the token was exchanged, or revoked explicitly. A second exchange "
            "of a revoked token is a replay, and kills its whole session."
        ),
    )

    objects = RefreshTokenQuerySet.as_manager()

    class Meta:
        verbose_name = "Refresh Token"
        verbose_name_plural = "Refresh Tokens"

    def __str__(self):
        return f"Refresh token {self.pk}"

    def is_usable(self, now=None) -> bool:
        now = now or timezone.now()
        return self.revoked_at is None and self.expires_at > now
