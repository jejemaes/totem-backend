from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Menu

from .common import (
    MENU_ID1,
    MENU_ID3,
    MENU_ID5,
    MENU_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

UNKNOWN_MENU_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"


class MenuDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `Menu`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = MENU_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/menus/display-name/"
        cls.ids = f"{MENU_ID5},{MENU_ID1},{MENU_ID3}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            (f"{MENU_ID3},{MENU_ID1}", 200, [MENU_ID3, MENU_ID1]),
            (f"{MENU_ID1},{MENU_ID3}", 200, [MENU_ID1, MENU_ID3]),
            # Blanks around the ids and empty items are dropped.
            (f" {MENU_ID1} ,,", 200, [MENU_ID1]),
            # An unknown id is absent, not an error.
            (f"{MENU_ID1},{UNKNOWN_MENU_ID}", 200, [MENU_ID1]),
            ("", 200, []),
            # A malformed id is the client's mistake.
            (f"{MENU_ID1},mordor", 422, None),
        ]
    )
    def test_display_name_request(self, ids, status_code, expected_pks):
        response = self.do_request("GET", self.url, params={"id": ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual([item["id"] for item in response.json()], expected_pks)
        else:
            self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])

    def test_display_name_response(self):
        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [MENU_ID5, MENU_ID1, MENU_ID3])
        for item in response.json():
            self.assert_api_format(item, Menu.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.read"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.read"], 403),
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
            (["totem.websitemenu.read"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.read"], 403),
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
