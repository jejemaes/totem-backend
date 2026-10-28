from django.test import TestCase
from parameterized import parameterized

from account.models import Budget
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import BUDGET_ID1, BUDGET_ID2, BUDGET_SCOPES, PERMISSION_DENIED, CommonTestMixin


class BudgetDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ Bag End 2026 (BUDGET_ID1) is in charge of Frodon, who acts; the Prancing
    Pony 2026 (BUDGET_ID2) of Gollum. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/budget/display-name/"
        cls.ids = f"{BUDGET_ID2},{BUDGET_ID1}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            ({"id": f"{BUDGET_ID2},{BUDGET_ID1}"}, 200, [BUDGET_ID2, BUDGET_ID1]),
            ({"id": f"{BUDGET_ID1},{BUDGET_ID2}"}, 200, [BUDGET_ID1, BUDGET_ID2]),
            # An unknown id is absent, not an error.
            ({"id": f"{BUDGET_ID1},01JB0000000000000000000099"}, 200, [BUDGET_ID1]),
            ({"id": ""}, 200, []),
            # A missing or malformed id is the client's mistake.
            ({}, 422, None),
            ({"id": f"{BUDGET_ID1},bag-end"}, 422, None),
        ]
    )
    def test_display_name_request(self, params, status_code, expected_pks):
        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual([item["id"] for item in response.json()], expected_pks)
        else:
            self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])

    def test_display_name_response(self):
        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        for item in response.json():
            self.assert_api_format(item, Budget.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.read"], 200),
            (["totem.budget.create", "totem.budget.update", "totem.budget.delete"], 403),
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
            (["totem.budget.read"], 200),
            (["totem.budget.create", "totem.budget.update", "totem.budget.delete"], 403),
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

    @parameterized.expand(
        [
            ([], [BUDGET_ID2, BUDGET_ID1]),
            # Out of reach, Gollum's budget is absent, exactly like an unknown id.
            (["budget_manage_own"], [BUDGET_ID1]),
            (["budget_manage_all"], [BUDGET_ID2, BUDGET_ID1]),
            (["budget_manage_own", "budget_manage_all"], [BUDGET_ID1]),
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
            (["budget_manage_own"],),
            (["budget_manage_all"],),
        ]
    )
    def test_display_name_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url, auth="apikey", params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [BUDGET_ID2, BUDGET_ID1])

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
