import dataclasses

from asgiref.sync import sync_to_async
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone

from authentication.models import ApiKey, RefreshToken
from authentication.schemas import ApiKeyCreateSchema
from authentication.tokens import encode_access_token, hash_secret
from core.services import CreateMixin, DeleteMixin, ReadMixin, Service, ServiceBase
from user.access_rights import get_user_scopes
from user.models import User


class InvalidCredentials(Exception):
    """ Unknown login, wrong password, or inactive account -- deliberately not
    told apart. """


class InvalidRefreshToken(Exception):
    """ Unknown refresh token, expired, already rotated (a replay), or belonging
    to a user who has since been deactivated. """


@dataclasses.dataclass(frozen=True, slots=True)
class TokenPair:
    """ What an exchange and a rotation both return. Not a record: see `AuthService`. """

    access_token: str
    refresh_token: str
    expires_in: int
    scope: str
    token_type: str = "Bearer"


class AuthService(Service):
    """ Exchange of credentials for a token pair, and rotation of that pair.

    A `Service` bound to no model, like `saas.services.TenantService`: what it
    returns is a pair of tokens, not a record. It writes the refresh row through
    the queryset directly, for the reason `TenantService` writes a fresh database
    with the ORM -- the caller is anonymous by construction, since it is in the
    middle of proving who it is, so there is no environment whose access rules
    could apply. The invariants (deriving the hash, setting the expiry) sit on
    `RefreshTokenQuerySet`, so they hold for any later writer too, not just this
    service.

    No `RefreshTokenService` is registered, and that is deliberate: handing
    `env[RefreshToken]` to generic code would expose a table of credentials that
    has no access rule -- and a model without a rule is readable by everyone
    (`apply_access_rules` assembles no lookup, so it filters nothing). Pinned by
    a test.

    Each public method makes a single hop to the sync world, as the other
    services do. `thread_sensitive=True` by default, which keeps the body on the
    calling thread: the same connection, hence the tenant database the middleware
    selected and the transaction a test wraps around itself.
    """

    async def login(self, username: str, password: str) -> TokenPair:
        return await sync_to_async(self._login)(username, password)

    async def refresh(self, refresh_secret: str) -> TokenPair:
        return await sync_to_async(self._refresh)(refresh_secret)

    async def revoke(self, refresh_secret: str) -> None:
        return await sync_to_async(self._revoke)(refresh_secret)

    # -----------------------------------------------------------------
    # Sync bodies
    # -----------------------------------------------------------------

    def _login(self, username, password):
        """ Verify the credentials and issue the first pair of a session.

        `django.contrib.auth.authenticate` rather than `user.check_password`, for
        three things it does that are easy to forget: `ModelBackend` refuses an
        inactive account (`user_can_authenticate`), it runs a password hash
        against a dummy user when the login is unknown so that the response time
        does not become an account enumeration oracle, and it emits
        `user_login_failed` for whatever watches it.
        """
        user = authenticate(username=username, password=password)
        if user is None:
            raise InvalidCredentials("Invalid credentials")

        now = timezone.now()
        with transaction.atomic():
            # `last_login` is written only by the `update_last_login` receiver on
            # `user_logged_in`, a signal `django.contrib.auth.login()` emits. A
            # token flow never calls it, so without this line the column would
            # stay null for every account, forever. Through the queryset, as the
            # services do -- and `UserQuerySet.update` only signals on
            # `user_type`, so this writes no rights change.
            User.objects.filter(pk=user.pk).update(last_login=now)
            return self._issue(user, now=now)

    def _refresh(self, refresh_secret):
        """ Rotate a pair: the presented token is spent, a successor is issued.

        The failure modes revoke rows and *then* report, so the report cannot
        happen inside the transaction that wrote them -- raising there would roll
        the revocation back and leave a replayed chain live. The transaction
        returns a verdict instead, and this raises once it has committed.
        """
        now = timezone.now()
        pair, failure = self._rotate(hash_secret(refresh_secret), now)
        if failure is not None:
            raise InvalidRefreshToken(failure)
        return pair

    def _rotate(self, secret_hash, now):
        """ The transactional body of a rotation: `(pair, None)` or `(None, reason)`. """
        with transaction.atomic():
            token = (
                RefreshToken.objects
                # `of=("self",)` so the lock covers the token row only: without
                # it, `select_related` would also lock the user row, and every
                # concurrent refresh of the same account would serialise on it.
                .select_for_update(of=("self",))
                .select_related("user")
                .filter(secret_hash=secret_hash)
                .first()
            )
            if token is None:
                return None, "Unknown refresh token"

            if token.revoked_at is not None:
                # A replay. Whoever presents it is either the legitimate client
                # repeating a request whose response it lost, or someone holding
                # a stolen copy -- and nothing here can tell the two apart, so the
                # whole chain goes (RFC 9700, 4.14.2). The accepted cost: a client
                # that loses a response signs itself out of that session.
                RefreshToken.objects.revoke_session(token.session_id, now=now)
                return None, "Refresh token replayed"

            if token.expires_at <= now:
                RefreshToken.objects.filter(pk=token.pk).revoke(now=now)
                return None, "Refresh token expired"

            if not token.user.is_active:
                # Deactivating an account takes effect immediately, here and in
                # the authenticator, which loads the user with `is_active=True` on
                # every request. Strictly better than the toolkit this replaces,
                # whose cached `AccessToken.user` never rechecked it.
                RefreshToken.objects.revoke_for_users(
                    User.objects.filter(pk=token.user_id), now=now
                )
                return None, "User is inactive"

            RefreshToken.objects.filter(pk=token.pk).revoke(now=now)
            return self._issue(token.user, session_id=token.session_id, now=now), None

    def _revoke(self, refresh_secret):
        """ End the session the given token belongs to.

        Reports nothing about whether it existed: the endpoint answers the same
        either way, so a caller cannot use it to probe which secrets are live.
        The whole chain goes, not just this token -- "sign out" means the session.
        """
        token = RefreshToken.objects.filter(secret_hash=hash_secret(refresh_secret)).first()
        if token is not None:
            RefreshToken.objects.revoke_session(token.session_id)

    def _issue(self, user, *, session_id=None, now=None) -> TokenPair:
        """ Mint an access token and a refresh token for `user`.

        The scopes are read from the live roles on every issuance, rotations
        included. That is the whole reason the refresh row carries no `scope`
        column: a right granted or withdrawn reaches the client within one access
        token lifetime, without anyone being signed out.
        """
        now = now or timezone.now()
        scopes = get_user_scopes(user)
        access_token, expires_at = encode_access_token(user.pk, scopes, now=now)
        dummy, refresh_secret = RefreshToken.objects.issue(user, session_id=session_id, now=now)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_secret,
            expires_in=int((expires_at - now).total_seconds()),
            scope=" ".join(scopes),
        )


class ApiKeyService(
    CreateMixin[ApiKeyCreateSchema],
    ReadMixin,
    DeleteMixin,
    ServiceBase[ApiKey],
):
    """ The machine-to-machine keys of the tenant.

    No `UpdateMixin`, and that absence is the guard: a secret is not edited, it
    is revoked and replaced, and widening the scopes of a key already in
    circulation would be a silent privilege escalation. Pinned by
    `assertFalse(hasattr(ApiKeyService, "update"))` and by the 405 a PATCH gets.

    No `validate_data` either, and that one is worth saying because writing one
    would be the obvious move: the only rule to enforce is that a scope be one of
    the registered public permissions, and that is a field-level `choices`, which
    is already enforced twice before any hook would run. Once by the generated
    schema, whose array field turns those choices into a pydantic enum -- so a bad
    scope is refused when `ApiKeyCreateSchema` is built, which is a 422 on the body
    rather than a service error -- and once by `to_internal_values`, for a caller
    that assembles values itself. A hook here would be dead code.

    The secret is derived by `ApiKeyQuerySet.bulk_create`, which is the only
    place it can be: `validate_data` runs before the instance exists, and the
    service write path never calls `Model.save()`.
    """

    def __init__(self, env):
        super().__init__(env)
        # The clear secrets minted in this unit of work, by pk.
        #
        # They have to be remembered somewhere, because the creation route
        # refetches the record from the database before serializing it -- so that a
        # response reads what the database derived -- and the clear secret is the
        # one value the database deliberately does not hold. `ApiKeyController`
        # carries it across that refetch from here.
        #
        # Request-scoped, not global: `Environment.get` builds one service instance
        # per environment, and no environment is ever shared between requests. The
        # same lifetime as `Environment._cache`.
        self._minted_secrets = {}

    async def create(self, data):
        instances = await super().create(data)
        self._minted_secrets.update(
            {instance.pk: instance.secret for instance in instances if instance.secret}
        )
        return instances

    def minted_secret(self, pk):
        """ The clear secret minted for `pk` in this unit of work, or `None`. """
        return self._minted_secrets.get(pk)
