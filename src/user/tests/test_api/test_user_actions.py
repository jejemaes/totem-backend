from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.models import User

from .common import USER_ID1, CommonTestMixin

USER_SCOPES = ["totem.user.create", "totem.user.read", "totem.user.update", "totem.user.delete"]

PROFILE_FIELDS = ["id", "login", "last_name", "first_name", "email", "language", "avatar"]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


@freeze_time("2024-11-18 11:12:13")
class UserActionsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The `/users/me/` routes: the profile of whoever is calling. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = USER_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url_profile = "/api/v1/users/me/"
        cls.payload_profile = {
            "login": "frodon.sacquet@lacomte.com",
            "first_name": "Frodon",
            "last_name": "Sacquet",
            "email": "frodon.sacquet@lacomte.com",
            "language": "en-us",
        }

    # ------------------------------------------
    # Profile Read
    # ------------------------------------------

    def test_profile_read_response(self):
        response = self.do_request("GET", self.url_profile)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), self.user_frodon)

    @parameterized.expand(
        [
            # The route asks for an authenticated user, no scope: reading one's own
            # profile is never a right to grant.
            ([], 200),
            (["totem.user.read"], 200),
            (["totem.userrole.read"], 200),
        ]
    )
    def test_profile_read_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_profile)

        self.assertEqual(response.status_code, status_code)

    @parameterized.expand(
        [
            # A key has no user, so no profile, whatever its scopes. See `IsAuthenticated`.
            ([],),
            (USER_SCOPES,),
        ]
    )
    def test_profile_read_apikey_access_rights(self, permissions):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_profile, auth="apikey")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Profile Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 200),
            ({"first_name": "Monsieur"}, 200),
            ({"first_name": None}, 200),
            ({"last_name": None}, 200),
            ({"email": "not an email"}, 422),
            ({"email": None}, 422),
            ({"language": "elvish"}, 422),
            ({"language": None}, 422),
            ({"login": None}, 422),
        ]
    )
    def test_profile_update_request(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_profile, data={**self.payload_profile, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))

    def test_profile_update_response(self):
        response = self.do_request("PATCH", self.url_profile, data=self.payload_profile)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), User.objects.get(pk=USER_ID1))
        self.assertEqual(User.objects.get(pk=USER_ID1).username, "frodon.sacquet@lacomte.com")

    @parameterized.expand(
        [
            ([], 200),
            (["totem.user.update"], 200),
            (["totem.userrole.read"], 200),
        ]
    )
    def test_profile_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_profile, data=self.payload_profile)

        self.assertEqual(response.status_code, status_code)

    @parameterized.expand(
        [
            ([],),
            (USER_SCOPES,),
        ]
    )
    def test_profile_update_apikey_access_rights(self, permissions):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_profile, auth="apikey", data=self.payload_profile)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or PROFILE_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "login" in fields:
            self.assertEqual(api_data["login"], obj.username)
        if "email" in fields:
            self.assertEqual(api_data["email"], obj.email)
        if "first_name" in fields:
            self.assertEqual(api_data["first_name"], obj.first_name)
        if "last_name" in fields:
            self.assertEqual(api_data["last_name"], obj.last_name)
        if "language" in fields:
            self.assertEqual(api_data["language"], obj.language)
        if "avatar" in fields:
            if obj.avatar:
                self.assertEqual(api_data["avatar"], obj.avatar.name)
            else:
                self.assertIn(api_data["avatar"], ("", None))

        self.assertEqual(set(fields), set(api_data))
