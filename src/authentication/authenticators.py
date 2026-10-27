"""The authentication callbacks the controllers declare in `auth`.

Each returns its own object, sharing only `ScopedPrincipalMixin`: see
`principal.py` for why there is no single principal type.
"""

import datetime

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from ninja.security import APIKeyHeader, HttpBearer

from authentication.models import ApiKey
from authentication.principal import AccessToken
from authentication.tokens import TokenError, decode_access_token, hash_secret
from user.models import User

__all__ = ["ApiKeyAuth", "JWTAuth"]


class JWTAuth(HttpBearer):
    """ A user's access token, in the `Authorization: Bearer` header.

    Two things this does *not* do, both deliberate. It does not look the token up
    in the database -- there is no row, the signature is the proof -- so the only
    query is the one that loads the user. And it does not prefetch the roles: the
    scopes come from the claim, and `Environment.get_access_roles()` already
    memoises the roles once per unit of work, so prefetching here would only make
    that query eager on the requests that never need it (`GET /users/me/` calls
    no service at all).

    The user is loaded with `is_active=True` on every request, which is what makes
    deactivating an account take effect immediately even though the token itself
    is stateless.
    """

    async def authenticate(self, request: HttpRequest, token: str):
        try:
            claims = decode_access_token(token)
        except TokenError:
            # Expired, forged, malformed or issued for another tenant database:
            # all of them are 401, and the client learns nothing from which.
            return None

        try:
            queryset = User.objects.filter(pk=claims["sub"], is_active=True)
        except (ValidationError, ValueError):
            # `sub` is not a well-formed identifier. Coercing the primary key
            # raises here, at `filter()` time, so without this the exception would
            # surface from the view and ninja would answer 500 where the honest
            # answer is 401.
            return None

        user = await queryset.afirst()
        if user is None:
            return None

        return AccessToken(
            user=user,
            scope=claims.get("scope", ""),
            jti=claims["jti"],
            expires_at=datetime.datetime.fromtimestamp(claims["exp"], tz=datetime.timezone.utc),
        )


class ApiKeyAuth(APIKeyHeader):
    """ A machine caller's key, in the `X-Api-Key` header.

    Returns the `ApiKey` row itself: it carries `ScopedPrincipalMixin`, so it
    already is what `request.auth` has to be. No wrapper, and `user` stays the
    `None` of the mixin.

    Django's `HttpHeaders` is case insensitive, so any casing a client sends
    arrives here.

    ⚠️ A request authenticated this way has no user, so it is subject to *no*
    row-level access rule: `Environment.get_access_roles()` returns `[]`,
    `apply_access_rules` assembles no lookup, and the queryset comes back
    unfiltered. A key holding `totem.user.read` therefore reads every user of the
    tenant, not a filtered subset. Coherent for a machine caller, and not what one
    guesses -- pinned by a test asserting the row count. Bounding a key would take
    an ownership column and a `BaseRule`, not a setting.
    """

    param_name = "X-Api-Key"

    async def authenticate(self, request: HttpRequest, key: str):
        if not key:
            return None
        # One indexed lookup on the digest, so no secret is ever compared in
        # Python -- hence no timing comparison to get right here. A `prefix.secret`
        # format, if it is ever added, would need `hmac.compare_digest`, as
        # `saas.security.SaasApiKey` does.
        return await ApiKey.objects.usable().filter(secret_hash=hash_secret(key)).afirst()
