from django.test import TestCase
from parameterized import parameterized

from account.models import AccountCategory
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SCOPES,
    CATEGORY_SHIRE_ID,
    PERMISSION_DENIED,
    CommonTestMixin,
)


class AccountCategoryDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `AccountCategory`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = CATEGORY_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/categories/display-name/"
        cls.ids = f"{CATEGORY_BREE_ID},{CATEGORY_GENERAL_ID},{CATEGORY_SHIRE_ID}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            (f"{CATEGORY_BREE_ID},{CATEGORY_GENERAL_ID}", 200, [CATEGORY_BREE_ID, CATEGORY_GENERAL_ID]),
            (f"{CATEGORY_GENERAL_ID},{CATEGORY_BREE_ID}", 200, [CATEGORY_GENERAL_ID, CATEGORY_BREE_ID]),
            # An unknown id is absent, not an error.
            (f"{CATEGORY_SHIRE_ID},01JC0000000000000000000099", 200, [CATEGORY_SHIRE_ID]),
            ("", 200, []),
            # A malformed id is the client's mistake.
            (f"{CATEGORY_SHIRE_ID},pipe-weed", 422, None),
            # Missing altogether.
            (None, 422, None),
        ]
    )
    def test_display_name_request(self, ids, status_code, expected_pks):
        params = {"id": ids} if ids is not None else {}

        response = self.do_request("GET", self.url, params=params)

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
            self.assert_api_format(item, AccountCategory.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.read"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.read"], 403),
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
            (["totem.accountcategory.read"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.read"], 403),
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
        self.assertEqual(api_data, {"id": obj.pk, "name": obj.name, "color": obj.color})
