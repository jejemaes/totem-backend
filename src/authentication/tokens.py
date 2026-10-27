"""Codec of the access tokens, and hashing of the opaque secrets.

Pure functions: no database, no request, no environment. That is what makes the
only cryptographic code of the project testable on its own, and what keeps it in
one readable file instead of spread over the authenticators that call it.
"""

import hashlib
import secrets
import uuid

import jwt
from django.conf import settings
from django.utils import timezone

from core.db.tenancy import current_database

__all__ = [
    "ACCESS_TOKEN_TYPE",
    "TokenError",
    "TokenExpired",
    "TokenInvalid",
    "decode_access_token",
    "encode_access_token",
    "generate_secret",
    "hash_secret",
]

ACCESS_TOKEN_TYPE = "access"

# Claims a token must carry to be considered at all. `exp` is the load-bearing
# one: pyjwt only validates the claims that are present, so without it here a
# token forged without an expiry would never expire. `db` is the tenant boundary
# (see `encode_access_token`).
REQUIRED_CLAIMS = ["exp", "iat", "sub", "typ", "jti", "db"]


class TokenError(Exception):
    """ Base of what `decode_access_token` raises. """


class TokenExpired(TokenError):
    """ The signature is valid but `exp` has passed. """


class TokenInvalid(TokenError):
    """ Malformed, wrongly signed, missing a required claim, of the wrong type,
    or issued for another tenant database. """


def encode_access_token(user_id, scopes, *, db_name=None, ttl=None, now=None):
    """ Return `(token, expires_at)` for the given user and scopes.

    The scopes are frozen into the token: an access token is never looked up in
    the database, so what it may do is decided once, here. They are sorted, so
    that the claim is deterministic -- two tokens minted from the same roles
    differ only by `iat` and `jti`, and a test can assert on the claim.

    `db_name` defaults to the database of the current unit of work, and is not
    optional in the payload: the signing key is shared by every tenant, so
    without this claim a token minted on one tenant database would verify on all
    the others. Looking `sub` up in the current database is not a boundary -- it
    is an identifier collision.

    Deliberately nothing else in the payload: no email, no username, no user
    type, no role, no `is_staff`. A bearer token ends up in proxy logs and in
    browser storage; it is a credential, not a profile cache. `/users/me/` is
    the profile endpoint.
    """
    now = now or timezone.now()
    ttl = ttl if ttl is not None else settings.JWT_ACCESS_TOKEN_LIFETIME
    expires_at = now + ttl
    payload = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "scope": " ".join(sorted(scopes or [])),
        "db": db_name or current_database(),
        "iat": now,
        "exp": expires_at,
        # One id per token: correlates the requests made with it in the logs, and
        # is the hook a denylist would need. It does not make a token revocable
        # on its own -- nothing reads it back today, and saying so is the point.
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token, *, db_name=None):
    """ Verify `token` and return its claims, or raise a `TokenError`.

    Nothing is trusted from the token itself: the algorithm is pinned to the one
    of the settings instead of being read from its header, which is what closes
    the algorithm confusion attack (`alg: none`, or HMAC against an RSA public
    key).

    No `nbf` is required, and none is emitted: it protects nothing here -- the
    issuer and the verifier are the same process -- while turning any clock skew
    between workers, or a `freeze_time` in a test, into a phantom 401.
    """
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.ExpiredSignatureError as exc:
        # Before `InvalidTokenError`, which it subclasses: an expired token is
        # the one failure the caller may want to tell a client about.
        raise TokenExpired(str(exc)) from exc
    except jwt.InvalidTokenError as exc:
        # A bad signature, a malformed token, a missing required claim and a
        # refused algorithm all land here. The caller answers 401 to each of
        # them, and telling them apart would only help forge the next one.
        raise TokenInvalid(str(exc)) from exc

    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        # Defence in depth: a refresh secret is not a JWT at all, so it cannot
        # reach this point. The claim keeps that true if another token type is
        # ever signed with the same key.
        raise TokenInvalid(f"Unexpected token type {claims.get('typ')!r}")

    expected_db = db_name or current_database()
    if claims.get("db") != expected_db:
        raise TokenInvalid(f"Token was not issued for the database {expected_db!r}")

    return claims


def generate_secret() -> str:
    """ A fresh opaque secret, for a refresh token or an API key.

    48 bytes of `secrets` entropy, urlsafe-encoded -- which is what lets
    `hash_secret` get away with an unsalted digest.
    """
    return secrets.token_urlsafe(48)


def hash_secret(secret: str) -> str:
    """ The 64-character hex SHA-256 of a secret, as stored.

    Unsalted SHA-256 is the right primitive here and pbkdf2 would be the wrong
    one, for three reasons that all follow from the input being 384 bits of
    `secrets` entropy rather than a human password: there is no dictionary
    attack to slow down, the digest has to be indexable for the lookup to stay a
    single indexed query, and a stretched verification on every authenticated
    request would dominate the latency of that request. Passwords are a
    different problem and keep Django's hashers.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()
