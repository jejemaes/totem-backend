from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Page

from .common import (
    PAGE_ID1,
    PAGE_ID2,
    PAGE_ID3,
    PAGE_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

UNKNOWN_PAGE_ID = "01M209K5BNS12QRPHXFWVJ0000"


class PageDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = PAGE_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/pages/display-name/"
        cls.ids = f"{PAGE_ID2},{PAGE_ID1},{PAGE_ID3}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            (f"{PAGE_ID2},{PAGE_ID1}", 200, [PAGE_ID2, PAGE_ID1]),
            (f"{PAGE_ID1},{PAGE_ID2}", 200, [PAGE_ID1, PAGE_ID2]),
            # A draft is a page like any other here.
            (PAGE_ID2, 200, [PAGE_ID2]),
            # Blanks around the ids and empty items are dropped.
            (f" {PAGE_ID1} ,,", 200, [PAGE_ID1]),
            # An unknown id is absent, not an error.
            (f"{PAGE_ID1},{UNKNOWN_PAGE_ID}", 200, [PAGE_ID1]),
            ("", 200, []),
            # A malformed id is the client's mistake.
            (f"{PAGE_ID1},shire", 422, None),
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
        self.assertEqual(len(response.json()), 3)
        for item in response.json():
            self.assert_api_format(item, Page.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.read"], 200),
            (["totem.websitepage.create", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.read"], 403),
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
            (["totem.websitepage.read"], 200),
            (["totem.websitepage.create", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.read"], 403),
        ]
    )
    def test_display_name_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey", params={"id": self.ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], [PAGE_ID2, PAGE_ID1, PAGE_ID3]),
            # An id out of reach is absent, exactly like an unknown one: Gollum's
            # page and the one with no author.
            (["website_manage_own_page"], [PAGE_ID1]),
        ]
    )
    def test_display_name_user_access_rules(self, rules, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], expected_pks)

    @parameterized.expand(
        [
            ([],),
            (["website_manage_own_page"],),
        ]
    )
    def test_display_name_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url, auth="apikey", params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [PAGE_ID2, PAGE_ID1, PAGE_ID3])

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
        self.assertEqual(api_data, {"id": obj.pk, "title": obj.title, "slug": obj.slug})
