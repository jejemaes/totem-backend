from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.models import UserRole

from .common import CommonTestMixin

ROLE_ID_BASE = "TEST_BASEUSER"  # the role of `CommonTestMixin`, held by Frodon
ROLE_ID1 = "FELLOWSHIP"
ROLE_ID2 = "MORDOR_ORCS"

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class UserRoleDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `UserRole`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        UserRole.objects.bulk_create(
            [
                UserRole(id=ROLE_ID1, name="Fellowship of the Ring"),
                UserRole(id=ROLE_ID2, name="Mordor Orcs"),
            ]
        )

        cls.role.permissions = ["totem.userrole.read"]
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/user-roles/display-name/"
        cls.ids = f"{ROLE_ID2},{ROLE_ID1},{ROLE_ID_BASE}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            (f"{ROLE_ID2},{ROLE_ID1}", [ROLE_ID2, ROLE_ID1]),
            (f"{ROLE_ID1},{ROLE_ID2}", [ROLE_ID1, ROLE_ID2]),
            # An unknown id is absent, not an error. Not shadowed by a retrieve:
            # the controller has none.
            (f"{ROLE_ID1},ISENGARD", [ROLE_ID1]),
            ("", []),
        ]
    )
    def test_display_name_request(self, ids, expected_pks):
        response = self.do_request("GET", self.url, params={"id": ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], expected_pks)

    def test_display_name_response(self):
        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 3)
        for item in response.json():
            self.assert_api_format(item, UserRole.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.read"], 403),
        ]
    )
    def test_display_name_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.read"], 403),
        ]
    )
    def test_display_name_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey", params={"id": self.ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
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

    def assert_api_format(self, api_data, obj):
        self.assertEqual(api_data, {"id": obj.pk, "name": obj.name})
