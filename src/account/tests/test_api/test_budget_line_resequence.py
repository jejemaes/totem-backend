import json

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import BudgetLine
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    BUDGET_ID1,
    BUDGET_ID2,
    BUDGET_SCOPES,
    LINE_ALE_ID,
    LINE_BREAKFAST_ID,
    LINE_PIPEWEED_ID,
    PERMISSION_DENIED,
    CommonTestMixin,
)

LINE_ID4 = "01JN0000000000000000000099"  # matches no line

OWN = "budget_line_manage_own"
ALL = "budget_line_manage_all"

# The lines of `CommonTestMixin` are created without a sequence: all at 10.
SEQUENCES = {LINE_BREAKFAST_ID: 10, LINE_PIPEWEED_ID: 10, LINE_ALE_ID: 10}


@freeze_time("2026-10-15 11:12:13")
class BudgetLineResequenceAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `/resequence/` numbers the lines of the budget of the path, and only them.

    It requires `totem.budget.update`: numbering lines is updating them.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/lines/resequence/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/lines/resequence/"
        cls.payload = {"ids": [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID]}

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            ("reversed", {"ids": [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID]}, 201, None,
             {LINE_PIPEWEED_ID: 1, LINE_BREAKFAST_ID: 2}),
            # Only the records given are numbered.
            ("partial", {"ids": [LINE_PIPEWEED_ID]}, 201, None, {LINE_PIPEWEED_ID: 1}),
            ("empty", {"ids": []}, 201, None, {}),
            ("offset_0", {"ids": [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], "offset": 0}, 201, None,
             {LINE_PIPEWEED_ID: 1, LINE_BREAKFAST_ID: 2}),
            # A page of a list: numbered where it sits in the whole list.
            ("offset", {"ids": [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], "offset": 20}, 201, None,
             {LINE_PIPEWEED_ID: 21, LINE_BREAKFAST_ID: 22}),
            ("unknown_pk", {"ids": [LINE_PIPEWEED_ID, LINE_ID4]}, 422, "ids", {}),
            ("not_a_ulid", {"ids": [LINE_PIPEWEED_ID, "not-a-ulid"]}, 422, "ids", {}),
            ("repeated_pk", {"ids": [LINE_PIPEWEED_ID, LINE_PIPEWEED_ID]}, 422, "ids", {}),
            # Another budget's line, through this budget's path.
            ("another_budgets", {"ids": [LINE_PIPEWEED_ID, LINE_ALE_ID]}, 422, "ids", {}),
            ("no_ids", {"offset": 0}, 422, "ids", {}),
            ("negative_offset", {"ids": [LINE_PIPEWEED_ID], "offset": -1}, 422, "offset", {}),
            ("offset_not_an_integer", {"ids": [LINE_PIPEWEED_ID], "offset": "first"}, 422, "offset", {}),
            # An object: neither a bare list nor anything else.
            ("a_bare_list", [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], 422, None, {}),
            ("a_string", LINE_PIPEWEED_ID, 422, None, {}),
        ]
    )
    def test_resequence_request(self, dummy, payload, status_code, error_field, renumbered):
        response = self.do_request("POST", self.url, data=json.dumps(payload))

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", error_field])
        # A refused request writes nothing; another budget's line is never touched.
        self.assertEqual(dict(BudgetLine.objects.values_list("id", "sequence")), {**SEQUENCES, **renumbered})

    def test_resequence_response(self):
        response = self.do_request("POST", self.url, data=json.dumps(self.payload))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content, b"")

    @parameterized.expand(
        [
            ([], 403),
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
            ([], BUDGET_ID2, [LINE_ALE_ID], 201),
            ([OWN], BUDGET_ID1, [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], 201),
            # Out of reach, Gollum's lines read as unknown: a 422, not a 404.
            ([OWN], BUDGET_ID2, [LINE_ALE_ID], 422),
            ([ALL], BUDGET_ID2, [LINE_ALE_ID], 201),
            ([OWN, ALL], BUDGET_ID2, [LINE_ALE_ID], 422),
        ]
    )
    def test_resequence_user_access_rules(self, rules, budget_id, pks, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{budget_id}/lines/resequence/", data=json.dumps({"ids": pks})
        )

        self.assertEqual(response.status_code, status_code)
        renumbered = {pk: index + 1 for index, pk in enumerate(pks)} if status_code == 201 else {}
        self.assertEqual(dict(BudgetLine.objects.values_list("id", "sequence")), {**SEQUENCES, **renumbered})

    @parameterized.expand(
        [
            ([],),
            ([OWN],),
            ([ALL],),
        ]
    )
    def test_resequence_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url_other, auth="apikey", data=json.dumps({"ids": [LINE_ALE_ID]}))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetLine.objects.get(pk=LINE_ALE_ID).sequence, 1)

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
