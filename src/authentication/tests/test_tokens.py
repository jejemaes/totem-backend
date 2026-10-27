import datetime

import jwt
from django.conf import settings
from django.test import SimpleTestCase, override_settings
from freezegun import freeze_time

from authentication.tokens import (
    TokenExpired,
    TokenInvalid,
    decode_access_token,
    encode_access_token,
    generate_secret,
    hash_secret,
)

# `SimpleTestCase`: the codec touches no database, and saying so here is half the
# point of it being a module of its own.


@freeze_time("2024-11-18 11:12:13")
class TestAccessTokenCodec(SimpleTestCase):

    def test_round_trip(self):
        token, expires_at = encode_access_token("user-1", ["totem.user.read"], db_name="totem")
        claims = decode_access_token(token, db_name="totem")

        self.assertEqual(claims["sub"], "user-1")
        self.assertEqual(claims["typ"], "access")
        self.assertEqual(claims["scope"], "totem.user.read")
        self.assertEqual(claims["db"], "totem")
        self.assertEqual(expires_at, datetime.datetime(2024, 11, 18, 11, 27, 13, tzinfo=datetime.timezone.utc))
        self.assertEqual(claims["exp"], int(expires_at.timestamp()))

    def test_scope_claim_is_sorted(self):
        # Deterministic claim: the same roles always produce the same string.
        token, dummy = encode_access_token(
            "user-1", ["totem.user.read", "totem.account.read", "totem.contact.read"], db_name="totem"
        )
        self.assertEqual(
            decode_access_token(token, db_name="totem")["scope"],
            "totem.account.read totem.contact.read totem.user.read",
        )

    def test_no_scope_is_an_empty_claim(self):
        token, dummy = encode_access_token("user-1", [], db_name="totem")
        self.assertEqual(decode_access_token(token, db_name="totem")["scope"], "")

    def test_jti_is_unique_per_token(self):
        first, dummy = encode_access_token("user-1", [], db_name="totem")
        second, dummy = encode_access_token("user-1", [], db_name="totem")
        self.assertNotEqual(
            decode_access_token(first, db_name="totem")["jti"],
            decode_access_token(second, db_name="totem")["jti"],
        )

    def test_expired_token(self):
        token, dummy = encode_access_token("user-1", [], db_name="totem")
        with freeze_time("2024-11-18 11:27:14"):
            with self.assertRaises(TokenExpired):
                decode_access_token(token, db_name="totem")

    def test_not_expired_one_second_before(self):
        token, dummy = encode_access_token("user-1", [], db_name="totem")
        with freeze_time("2024-11-18 11:27:12"):
            self.assertEqual(decode_access_token(token, db_name="totem")["sub"], "user-1")

    def test_tampered_payload(self):
        token, dummy = encode_access_token("user-1", [], db_name="totem")
        header, payload, signature = token.split(".")
        forged, dummy = encode_access_token("user-2", ["totem.user.delete"], db_name="totem")
        with self.assertRaises(TokenInvalid):
            decode_access_token(f"{header}.{forged.split('.')[1]}.{signature}", db_name="totem")

    def test_foreign_signing_key(self):
        with override_settings(JWT_SIGNING_KEY="another-key-entirely"):
            token, dummy = encode_access_token("user-1", [], db_name="totem")
        with self.assertRaises(TokenInvalid):
            decode_access_token(token, db_name="totem")

    def test_unsigned_token_is_refused(self):
        # The algorithm confusion attack: a token asserting its own `alg`. The
        # decoder pins the algorithm instead of reading the header, so this is a
        # plain signature failure.
        payload = {
            "sub": "user-1",
            "typ": "access",
            "scope": "",
            "db": "totem",
            "iat": 1731928333,
            "exp": 9999999999,
            "jti": "deadbeef",
        }
        token = jwt.encode(payload, key=None, algorithm="none")
        with self.assertRaises(TokenInvalid):
            decode_access_token(token, db_name="totem")

    def test_wrong_token_type(self):
        payload = {
            "sub": "user-1",
            "typ": "refresh",
            "scope": "",
            "db": "totem",
            "iat": 1731928333,
            "exp": 9999999999,
            "jti": "deadbeef",
        }
        token = jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM)
        with self.assertRaises(TokenInvalid):
            decode_access_token(token, db_name="totem")

    def test_missing_required_claim(self):
        # Without `exp` in the required claims, pyjwt would validate nothing and
        # this token would be immortal.
        for missing in ("exp", "iat", "sub", "typ", "jti", "db"):
            with self.subTest(missing=missing):
                payload = {
                    "sub": "user-1",
                    "typ": "access",
                    "scope": "",
                    "db": "totem",
                    "iat": 1731928333,
                    "exp": 9999999999,
                    "jti": "deadbeef",
                }
                del payload[missing]
                token = jwt.encode(
                    payload, settings.JWT_SIGNING_KEY, algorithm=settings.JWT_ALGORITHM
                )
                with self.assertRaises(TokenInvalid):
                    decode_access_token(token, db_name="totem")

    def test_token_of_another_tenant(self):
        # The one property the `db` claim exists for: the signing key is shared
        # by every tenant, so without it this token would verify here.
        token, dummy = encode_access_token("user-1", [], db_name="tenant_a")
        with self.assertRaises(TokenInvalid):
            decode_access_token(token, db_name="tenant_b")

    def test_garbage_is_not_a_token(self):
        for value in ("", "garbage", "a.b.c", "Bearer something"):
            with self.subTest(value=value):
                with self.assertRaises(TokenInvalid):
                    decode_access_token(value, db_name="totem")


class TestSecretHashing(SimpleTestCase):

    def test_generate_secret_is_unique_and_urlsafe(self):
        secrets_seen = {generate_secret() for dummy in range(100)}
        self.assertEqual(len(secrets_seen), 100)
        for secret in secrets_seen:
            self.assertRegex(secret, r"^[A-Za-z0-9_-]+$")

    def test_hash_is_stable_64_hex(self):
        secret = generate_secret()
        self.assertEqual(hash_secret(secret), hash_secret(secret))
        self.assertRegex(hash_secret(secret), r"^[0-9a-f]{64}$")

    def test_hash_differs_per_secret(self):
        self.assertNotEqual(hash_secret("a"), hash_secret("b"))
