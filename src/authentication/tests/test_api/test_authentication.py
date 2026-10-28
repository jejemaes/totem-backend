import datetime

import jwt
from django.conf import settings
from django.test import Client, TestCase, override_settings
from freezegun import freeze_time

from authentication.testing import mint_access_token, public_scopes
from authentication.tokens import encode_access_token
from core.testing import APITestCaseMixin
from user.models import UserRole
from user.tests.test_api.common import CommonTestMixin

USERS_URL = "/api/v1/users/"


@freeze_time("2024-11-18 11:12:13")
class AuthenticationAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The 401 surface of the API: what a bad or absent credential gets.

    There was no coverage of it at all under the toolkit -- every API test
    arrived with a valid token -- which is how `Request._get_request_user` kept a
    reachable fallback to `AnonymousUser` nobody noticed.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        UserRole.objects.filter(pk=cls.role.pk).update(permissions=public_scopes())

    def get_users(self, **headers):
        return Client().get(USERS_URL, **headers)

    def bearer(self, token):
        return self.get_users(HTTP_AUTHORIZATION=f"Bearer {token}")

    # ------------------------------------------
    # No credential
    # ------------------------------------------

    def test_no_header_at_all(self):
        response = self.get_users()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})

    def test_malformed_authorization_headers(self):
        for value in ["", "Bearer", "Bearer ", "Basic abc", "Token abc", "abc"]:
            with self.subTest(value=value):
                response = self.get_users(HTTP_AUTHORIZATION=value)
                self.assertEqual(response.status_code, 401)

    def test_garbage_bearer(self):
        for value in ["garbage", "a.b.c", "x" * 500]:
            with self.subTest(value=value):
                self.assertEqual(self.bearer(value).status_code, 401)

    # ------------------------------------------
    # A token that does not verify
    # ------------------------------------------

    def test_a_valid_token_is_accepted(self):
        # The control: everything below differs from this by one thing only.
        token = mint_access_token(self.user_frodon, ["totem.user.read"])
        self.assertEqual(self.bearer(token).status_code, 200)

    def test_an_expired_token(self):
        token = mint_access_token(self.user_frodon, ["totem.user.read"])
        with freeze_time("2024-11-18 11:27:14"):
            self.assertEqual(self.bearer(token).status_code, 401)

    def test_a_token_signed_with_another_key(self):
        with override_settings(JWT_SIGNING_KEY="another-key-entirely"):
            token = mint_access_token(self.user_frodon, ["totem.user.read"])
        self.assertEqual(self.bearer(token).status_code, 401)

    def test_an_unsigned_token(self):
        payload = {
            "sub": str(self.user_frodon.pk),
            "typ": "access",
            "scope": "totem.user.read",
            "db": "postgres",
            "iat": 1731928333,
            "exp": 9999999999,
            "jti": "deadbeef",
        }
        token = jwt.encode(payload, key=None, algorithm="none")
        self.assertEqual(self.bearer(token).status_code, 401)

    def test_a_token_for_another_database(self):
        token, dummy = encode_access_token(
            self.user_frodon.pk, ["totem.user.read"], db_name="some_other_tenant"
        )
        self.assertEqual(self.bearer(token).status_code, 401)

    # ------------------------------------------
    # A token that verifies but names nobody usable
    # ------------------------------------------

    def test_an_unknown_subject(self):
        token, dummy = encode_access_token(
            "c99199ba-8fa5-461e-802e-000000000000", ["totem.user.read"]
        )
        self.assertEqual(self.bearer(token).status_code, 401)

    def test_a_malformed_subject_is_401_and_not_500(self):
        # The primary key is a UUID, so coercing this raises inside `filter()`.
        # Uncaught, ninja would answer 500 where the honest answer is 401.
        token, dummy = encode_access_token("not-a-uuid", ["totem.user.read"])
        self.assertEqual(self.bearer(token).status_code, 401)

    def test_a_deactivated_user(self):
        # The immediacy a stateless token is supposed to cost us, and does not:
        # the user is loaded with `is_active=True` on every single request.
        token = mint_access_token(self.user_frodon, ["totem.user.read"])
        self.assertEqual(self.bearer(token).status_code, 200)

        type(self.user_frodon).objects.filter(pk=self.user_frodon.pk).update(is_active=False)

        self.assertEqual(self.bearer(token).status_code, 401)

    # ------------------------------------------
    # Crossing the two credentials
    # ------------------------------------------

    def test_a_refresh_token_is_not_a_bearer_token(self):
        from authentication.models import RefreshToken

        dummy, secret = RefreshToken.objects.issue(self.user_frodon)
        self.assertEqual(self.bearer(secret).status_code, 401)

    def test_an_api_key_in_the_wrong_header(self):
        self.assertEqual(self.bearer(self.api_key_secret).status_code, 401)

    def test_an_access_token_in_the_wrong_header(self):
        token = mint_access_token(self.user_frodon, ["totem.user.read"])
        response = self.get_users(HTTP_X_API_KEY=token)
        self.assertEqual(response.status_code, 401)

    def test_the_jwt_wins_when_both_headers_are_sent(self):
        """ `auth` is an ordered list and ninja stops at the first callback that
        returns something, so `JWTAuth` decides. Asserted because the answer
        differs: a key has no user, and `/users/me/` needs one. """
        token = mint_access_token(self.user_frodon, ["totem.user.read"])

        response = Client().get(
            "/api/v1/users/me/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_API_KEY=self.api_key_secret,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.user_frodon.pk))

    def test_expiry_is_proven_before_the_scope_is_read(self):
        # An expired token holding every scope is still a 401, not a 403: the
        # signature check runs before any permission does.
        token = mint_access_token(self.user_frodon)
        with freeze_time("2024-11-18 11:27:14"):
            response = self.bearer(token)
        self.assertEqual(response.status_code, 401)
        self.assertNotEqual(response.status_code, 403)
