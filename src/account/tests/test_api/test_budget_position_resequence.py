import json

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

# The sequences of `CommonTestMixin`; Ale keeps the default.
INITIAL_SEQUENCES = {POSITION_BREAKFAST_ID: 1, POSITION_PIPEWEED_ID: 2, POSITION_ALE_ID: 10}


class BudgetPositionResequenceAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `POST /accounting/budget/{budget_id}/positions/resequence/`: numbers the
    positions of the budget of the path only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/resequence/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/resequence/"
        cls.payload = {"ids": [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]}

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            ("reversed", {"ids": [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]}, 201, None,
             {POSITION_PIPEWEED_ID: 1, POSITION_BREAKFAST_ID: 2}),
            # Only the records given are numbered.
            ("partial", {"ids": [POSITION_PIPEWEED_ID]}, 201, None, {POSITION_PIPEWEED_ID: 1}),
            ("empty", {"ids": []}, 201, None, {}),
            ("offset 0", {"ids": [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], "offset": 0}, 201, None,
             {POSITION_PIPEWEED_ID: 1, POSITION_BREAKFAST_ID: 2}),
            # A page of a list: numbered where it sits in the whole list.
            ("page of a list", {"ids": [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], "offset": 20}, 201, None,
             {POSITION_PIPEWEED_ID: 21, POSITION_BREAKFAST_ID: 22}),
            ("unknown pk", {"ids": [POSITION_PIPEWEED_ID, POSITION_ID4]}, 422, "ids", {}),
            ("not a ulid", {"ids": [POSITION_PIPEWEED_ID, "not-a-ulid"]}, 422, "ids", {}),
            ("repeated pk", {"ids": [POSITION_PIPEWEED_ID, POSITION_PIPEWEED_ID]}, 422, "ids", {}),
            # Another budget's position reads as unknown under this one.
            ("another budget's", {"ids": [POSITION_PIPEWEED_ID, POSITION_ALE_ID]}, 422, "ids", {}),
            ("no ids", {"offset": 0}, 422, "ids", {}),
            ("negative offset", {"ids": [POSITION_PIPEWEED_ID], "offset": -1}, 422, "offset", {}),
            ("offset not an integer", {"ids": [POSITION_PIPEWEED_ID], "offset": "first"}, 422, "offset", {}),
            # An object: neither a bare list nor anything else.
            ("a bare list", [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], 422, None, {}),
            ("a string", POSITION_PIPEWEED_ID, 422, None, {}),
        ]
    )
    def test_resequence_request(self, dummy, payload, status_code, error_field, changed):
        response = self.do_request("POST", self.url, data=json.dumps(payload))

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", error_field])
        # Nothing is written on an error, and another budget's position never is.
        self.assertEqual(
            dict(BudgetPosition.objects.values_list("id", "sequence")), {**INITIAL_SEQUENCES, **changed}
        )

    def test_resequence_response(self):
        response = self.do_request("POST", self.url, data=json.dumps(self.payload))

        self.assertEqual(response.status_code, 201)
        # No body, hence no `assert_api_format` in this class.
        self.assertEqual(response.content, b"")

    @parameterized.expand(
        [
            ([], 403),
            # Numbering the positions of a budget is updating it.
            (["totem.budget.update"], 201),
            (["totem.budget.create", "totem.budget.read", "totem.budget.delete"], 403),
            (["totem.account.update"], 403),
        ]
    )
    def test_resequence_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=json.dumps(self.payload))

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.update"], 201),
            (["totem.budget.create", "totem.budget.read", "totem.budget.delete"], 403),
            (["totem.account.update"], 403),
        ]
    )
    def test_resequence_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=json.dumps(self.payload))

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID2, [POSITION_ALE_ID], 201),
            (["budget_position_manage_own"], BUDGET_ID1, [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], 201),
            # Out of reach, Gollum's position reads as unknown.
            (["budget_position_manage_own"], BUDGET_ID2, [POSITION_ALE_ID], 422),
            (["budget_position_manage_all"], BUDGET_ID2, [POSITION_ALE_ID], 201),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, [POSITION_ALE_ID], 422),
        ]
    )
    def test_resequence_user_access_rules(self, rules, budget_id, pks, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{budget_id}/positions/resequence/", data=json.dumps({"ids": pks})
        )

        self.assertEqual(response.status_code, status_code)
        changed = {pk: index + 1 for index, pk in enumerate(pks)} if status_code == 201 else {}
        self.assertEqual(
            dict(BudgetPosition.objects.values_list("id", "sequence")), {**INITIAL_SEQUENCES, **changed}
        )

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_resequence_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url_other, auth="apikey", data=json.dumps({"ids": [POSITION_ALE_ID]}))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_ALE_ID).sequence, 1)

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
