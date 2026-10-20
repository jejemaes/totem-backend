from django.test import TestCase
from parameterized import parameterized

from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    ACCOUNT_ID3,
    BUDGET_ID1,
    BUDGET_ID2,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    POSITION_FEES_ID,
    POSITION_RENT_ID,
    POSITION_STOCK_ID,
    BudgetTestMixin,
)
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class AccountingDisplayNameAPITest(BudgetTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):
    """`GET .../display-name/?id=...` on the accounting resources."""

    def request(self, url, ids, token=None):
        return self.do_api_request(
            url, "GET", token or self.user_access_token_frodon.token, params={"id": ",".join(ids)}
        )

    # ------------------------------------------
    # Response
    # ------------------------------------------

    def test_accounts(self):
        response = self.request("/api/v1/accounting/accounts/display-name/", [ACCOUNT_ID3, ACCOUNT_ID1])

        self.assertEqual(response.status_code, 200)
        # In the order asked, inactive included: a label is read, not a list filtered.
        self.assertEqual(
            response.json(),
            [
                {"id": ACCOUNT_ID3, "code": "OLD", "name": "Old shop"},
                {"id": ACCOUNT_ID1, "code": "SHOP", "name": "Shop"},
            ],
        )

    def test_account_categories(self):
        response = self.request("/api/v1/accounting/categories/display-name/", [CATEGORY_BANK_ID, CATEGORY_GENERAL_ID])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"id": CATEGORY_BANK_ID, "name": "Fees", "color": self.category_bank.color},
                {"id": CATEGORY_GENERAL_ID, "name": "Rent", "color": self.category_general.color},
            ],
        )

    def test_budgets(self):
        response = self.request("/api/v1/accounting/budget/display-name/", [BUDGET_ID2, BUDGET_ID1])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), [{"id": BUDGET_ID2, "name": "Bank 2026"}, {"id": BUDGET_ID1, "name": "Shop 2026"}]
        )

    def test_budget_positions_within_the_path(self):
        # Fees is another budget's position: absent, as an unknown id.
        response = self.request(
            f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/display-name/",
            [POSITION_STOCK_ID, POSITION_FEES_ID, POSITION_RENT_ID],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [POSITION_STOCK_ID, POSITION_RENT_ID])
        self.assertEqual(set(response.json()[0]), {"id", "name", "color"})

    def test_unknown_id(self):
        response = self.request("/api/v1/accounting/accounts/display-name/", ["01JA0000000000000000000099"])

        self.assertEqual((response.status_code, response.json()), (200, []))

    @parameterized.expand([("missing", None), ("not a ulid", "SHOP")])
    def test_invalid_ids(self, dummy, ids):
        params = {"id": ids} if ids is not None else {}
        response = self.do_api_request(
            "/api/v1/accounting/accounts/display-name/", "GET", self.user_access_token_frodon.token, params=params
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])

    # ------------------------------------------
    # Access
    # ------------------------------------------

    @parameterized.expand(
        [
            ("/api/v1/accounting/accounts/", ACCOUNT_ID1, "totem.account.read", 200),
            ("/api/v1/accounting/accounts/", ACCOUNT_ID1, "totem.account.update", 403),
            ("/api/v1/accounting/accounts/", ACCOUNT_ID1, "totem.accountcategory.read", 403),
            ("/api/v1/accounting/categories/", CATEGORY_BANK_ID, "totem.accountcategory.read", 200),
            ("/api/v1/accounting/categories/", CATEGORY_BANK_ID, "totem.account.read", 403),
            ("/api/v1/accounting/budget/", BUDGET_ID1, "totem.budget.read", 200),
            ("/api/v1/accounting/budget/", BUDGET_ID1, "totem.budget.update", 403),
            (f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/", POSITION_RENT_ID, "totem.budget.read", 200),
            (f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/", POSITION_RENT_ID, "totem.budget.update", 403),
        ]
    )
    def test_access_rights(self, url, pk, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.request(f"{url}display-name/", [pk])

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            # Out of scope, another user's budget reads as unknown.
            ("BUDGET_USER", "/api/v1/accounting/budget/", [BUDGET_ID2, BUDGET_ID1], [BUDGET_ID1]),
            ("BUDGET_READER", "/api/v1/accounting/budget/", [BUDGET_ID2, BUDGET_ID1], [BUDGET_ID2, BUDGET_ID1]),
            ("BUDGET_USER", f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/", [POSITION_FEES_ID], []),
            ("BUDGET_READER", f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/", [POSITION_FEES_ID], [POSITION_FEES_ID]),
        ]
    )
    def test_access_rules(self, role, url, pks, expected):
        response = self.request(f"{url}display-name/", pks, token=self.token_as(role))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], expected)
