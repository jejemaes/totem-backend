import json

from django.test import Client, TestCase
from freezegun import freeze_time

from authentication.models import RefreshToken
from authentication.tokens import decode_access_token, hash_secret
from core.testing import APITestCaseMixin
from user.models import UserRole
from user.tests.test_api.common import CommonTestMixin

PASSWORD = "a-perfectly-fine-password"

TOKEN_FIELDS = {"access_token", "refresh_token", "token_type", "expires_in", "scope"}


@freeze_time("2024-11-18 11:12:13")
class AuthAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url_token = "/api/v1/auth/token/"
        cls.url_refresh = "/api/v1/auth/token/refresh/"
        cls.url_revoke = "/api/v1/auth/token/revoke/"
        cls.url_profile = "/api/v1/users/me/"

        # The fixture users are built with `User.objects.create()`, which leaves an
        # unusable password hash: nobody could log in without this.
        cls.user_frodon.set_password(PASSWORD)
        cls.user_frodon.save(update_fields=["password"])

        UserRole.objects.filter(pk=cls.role.pk).update(
            permissions=["totem.user.read", "totem.contact.read"]
        )

    def post(self, url, payload):
        """ A request with no credential at all: these routes are public, which is
        the point of `AuthController.auth = None`. `do_api_request` always builds
        an Authorization header, so it cannot be used here. """
        return Client().post(url, json.dumps(payload), content_type="application/json")

    def login(self, username=None, password=PASSWORD):
        return self.post(
            self.url_token,
            {"username": username or self.user_frodon.username, "password": password},
        )

    # ------------------------------------------
    # Tests Token
    # ------------------------------------------

    def test_token_create(self):
        response = self.login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body.keys()), TOKEN_FIELDS)
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(body["expires_in"], 900)
        self.assertEqual(body["scope"], "totem.contact.read totem.user.read")

        claims = decode_access_token(body["access_token"])
        self.assertEqual(claims["sub"], str(self.user_frodon.pk))
        self.assertEqual(claims["scope"], body["scope"])

    def test_token_create_stores_only_the_hash(self):
        body = self.login().json()

        token = RefreshToken.objects.get()
        # Compared as strings: the fixture builds the user with a literal `id`, so
        # its in-memory pk is a `str` while the one read back is a `UUID`.
        self.assertEqual(str(token.user_id), str(self.user_frodon.pk))
        self.assertEqual(token.secret_hash, hash_secret(body["refresh_token"]))
        self.assertNotEqual(token.secret_hash, body["refresh_token"])

    def test_the_route_needs_no_credential(self):
        # Asserted explicitly: it is the one controller of the project with
        # `auth = None`, and a stray `auth` on it would 401 everyone out of the
        # only way in.
        self.assertEqual(self.login().status_code, 200)

    def test_the_token_authenticates_a_real_request(self):
        access_token = self.login().json()["access_token"]

        response = self.do_api_request(self.url_profile, "GET", access_token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], str(self.user_frodon.pk))

    def test_every_failure_answers_the_same(self):
        self.user_gollum.is_active = False
        self.user_gollum.set_password(PASSWORD)
        self.user_gollum.save(update_fields=["password", "is_active"])

        cases = {
            "wrong password": self.login(password="not-the-password"),
            "unknown login": self.login(username="nobody@nowhere.com"),
            "inactive account": self.login(username=self.user_gollum.username),
            # A fixture user, so an unusable hash.
            "unusable password": self.login(username="gollum@precious.com"),
        }
        for label, response in cases.items():
            with self.subTest(case=label):
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Invalid credentials."})

        self.assertFalse(RefreshToken.objects.exists())

    def test_a_missing_field_is_a_422(self):
        for payload in ({}, {"username": "frodon@lacomte.com"}, {"password": PASSWORD}):
            with self.subTest(payload=payload):
                self.assertEqual(self.post(self.url_token, payload).status_code, 422)

    def test_an_unknown_field_is_refused(self):
        # `extra="forbid"` on the schema: a client sending `client_id` out of
        # OAuth2 habit should hear about it, not have it silently ignored.
        response = self.post(
            self.url_token,
            {"username": self.user_frodon.username, "password": PASSWORD, "client_id": "x"},
        )
        self.assertEqual(response.status_code, 422)

    # ------------------------------------------
    # Tests Refresh
    # ------------------------------------------

    def test_token_refresh(self):
        first = self.login().json()

        response = self.post(self.url_refresh, {"refresh_token": first["refresh_token"]})

        self.assertEqual(response.status_code, 200)
        second = response.json()
        self.assertEqual(set(second.keys()), TOKEN_FIELDS)
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.assertEqual(RefreshToken.objects.count(), 2)
        self.assertEqual(RefreshToken.objects.active().count(), 1)

    def test_the_rotated_token_authenticates_a_real_request(self):
        first = self.login().json()
        second = self.post(self.url_refresh, {"refresh_token": first["refresh_token"]}).json()

        response = self.do_api_request(self.url_profile, "GET", second["access_token"])

        self.assertEqual(response.status_code, 200)

    def test_refresh_recomputes_the_scopes(self):
        first = self.login().json()
        UserRole.objects.filter(pk=self.role.pk).update(permissions=["totem.user.read"])

        second = self.post(self.url_refresh, {"refresh_token": first["refresh_token"]}).json()

        self.assertEqual(second["scope"], "totem.user.read")

    def test_a_replayed_refresh_token_kills_the_session(self):
        first = self.login().json()
        second = self.post(self.url_refresh, {"refresh_token": first["refresh_token"]}).json()

        replay = self.post(self.url_refresh, {"refresh_token": first["refresh_token"]})

        self.assertEqual(replay.status_code, 401)
        self.assertEqual(replay.json(), {"detail": "Invalid refresh token."})
        # The successor goes down with it: nothing distinguishes a client that lost
        # a response from someone holding a stolen copy.
        after = self.post(self.url_refresh, {"refresh_token": second["refresh_token"]})
        self.assertEqual(after.status_code, 401)

    def test_refresh_of_an_unknown_token(self):
        response = self.post(self.url_refresh, {"refresh_token": "never-issued"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Invalid refresh token."})

    def test_an_access_token_is_not_a_refresh_token(self):
        body = self.login().json()

        response = self.post(self.url_refresh, {"refresh_token": body["access_token"]})

        self.assertEqual(response.status_code, 401)

    # ------------------------------------------
    # Tests Revoke
    # ------------------------------------------

    def test_token_revoke(self):
        body = self.login().json()

        response = self.post(self.url_revoke, {"refresh_token": body["refresh_token"]})

        self.assertEqual(response.status_code, 204)
        self.assertFalse(RefreshToken.objects.active().exists())
        self.assertEqual(
            self.post(self.url_refresh, {"refresh_token": body["refresh_token"]}).status_code,
            401,
        )

    def test_revoke_says_nothing_about_an_unknown_token(self):
        # 204 either way, so the endpoint cannot be used to probe which refresh
        # secrets are live.
        response = self.post(self.url_revoke, {"refresh_token": "never-issued"})

        self.assertEqual(response.status_code, 204)

    def test_revoking_does_not_invalidate_the_access_token(self):
        """ The honest consequence of a stateless access token.

        Revoking ends the *session*: no new access token can be minted. The one
        already issued stays valid until it expires, at most 15 minutes. Asserted
        so that nobody reads "revoke" as "sign out immediately".
        """
        body = self.login().json()

        self.post(self.url_revoke, {"refresh_token": body["refresh_token"]})

        response = self.do_api_request(self.url_profile, "GET", body["access_token"])
        self.assertEqual(response.status_code, 200)
