from django.test import TestCase
from parameterized import parameterized

from account.models import BudgetPosition
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    BUDGET_ID1,
    BUDGET_ID2,
    BUDGET_SCOPES,
    PERMISSION_DENIED,
    POSITION_ALE_ID,
    POSITION_BREAKFAST_ID,
    POSITION_PIPEWEED_ID,
    CommonTestMixin,
)

POSITION_ID4 = "01JP0000000000000000000099"  # matches no position


class BudgetPositionDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `GET /accounting/budget/{budget_id}/positions/display-name/`: within the
    budget of the path, like every route of the positions. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/display-name/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/display-name/"
        cls.ids = f"{POSITION_PIPEWEED_ID},{POSITION_BREAKFAST_ID}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            (f"{POSITION_PIPEWEED_ID},{POSITION_BREAKFAST_ID}", 200, [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]),
            (f"{POSITION_BREAKFAST_ID},{POSITION_PIPEWEED_ID}", 200, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            # Another budget's position is absent, as an unknown id.
            (f"{POSITION_PIPEWEED_ID},{POSITION_ALE_ID},{POSITION_BREAKFAST_ID}", 200, [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]),
            (f"{POSITION_BREAKFAST_ID},{POSITION_ID4}", 200, [POSITION_BREAKFAST_ID]),
            ("", 200, []),
            # A malformed id is the client's mistake.
            (f"{POSITION_BREAKFAST_ID},second-breakfast", 422, None),
            (None, 422, None),  # no `id` at all
        ]
    )
    def test_display_name_request(self, ids, status_code, expected_pks):
        response = self.do_request("GET", self.url, params={"id": ids} if ids is not None else {})

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
            self.assert_api_format(item, BudgetPosition.objects.get(pk=item["id"]))

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
            ([], BUDGET_ID2, [POSITION_ALE_ID]),
            (["budget_position_manage_own"], BUDGET_ID1, [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]),
            # Out of reach, Gollum's position is absent, exactly like an unknown one.
            (["budget_position_manage_own"], BUDGET_ID2, []),
            (["budget_position_manage_all"], BUDGET_ID2, [POSITION_ALE_ID]),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, []),
        ]
    )
    def test_display_name_user_access_rules(self, rules, budget_id, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "GET", f"/api/v1/accounting/budget/{budget_id}/positions/display-name/",
            params={"id": f"{POSITION_PIPEWEED_ID},{POSITION_ALE_ID},{POSITION_BREAKFAST_ID}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], expected_pks)

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_display_name_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url_other, auth="apikey", params={"id": POSITION_ALE_ID})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [POSITION_ALE_ID])

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
        # The name and the color are those of the category.
        self.assertEqual(api_data, {"id": obj.pk, "name": obj.name, "color": obj.color})
