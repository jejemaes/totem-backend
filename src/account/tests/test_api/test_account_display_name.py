from django.test import TestCase
from parameterized import parameterized

from account.models import Account
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    ACCOUNT_ID3,
    ACCOUNT_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)


class AccountDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `Account`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = ACCOUNT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/accounts/display-name/"
        cls.ids = f"{ACCOUNT_ID3},{ACCOUNT_ID1},{ACCOUNT_ID2}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned, inactive included: a label is
            # read, not a list filtered.
            (f"{ACCOUNT_ID3},{ACCOUNT_ID1}", 200, [ACCOUNT_ID3, ACCOUNT_ID1]),
            (f"{ACCOUNT_ID1},{ACCOUNT_ID3}", 200, [ACCOUNT_ID1, ACCOUNT_ID3]),
            # An unknown id is absent, not an error.
            (f"{ACCOUNT_ID1},01JA0000000000000000000099", 200, [ACCOUNT_ID1]),
            ("01JA0000000000000000000099", 200, []),
            # A malformed id is the client's mistake.
            ("SHIRE", 422, None),
            (None, 422, None),  # missing
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
            self.assert_api_format(item, Account.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.read"], 200),
            (["totem.account.create", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountcategory.read"], 403),
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
            (["totem.account.read"], 200),
            (["totem.account.create", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountcategory.read"], 403),
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
        self.assertEqual(api_data, {"id": str(obj.pk), "code": obj.code, "name": obj.name})
