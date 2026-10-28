from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountCategory, BudgetLine, BudgetPosition, Budget
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    BUDGET_ID1,
    BUDGET_ID2,
    BUDGET_SCOPES,
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    PERMISSION_DENIED,
    POSITION_ALE_ID,
    POSITION_BREAKFAST_ID,
    POSITION_PIPEWEED_ID,
    CommonTestMixin,
)

POSITION_ID4 = "01JP0000000000000000000099"  # matches no position
BUDGET_ID3 = "01JB0000000000000000000099"  # matches no budget

POSITION_FIELDS = ["id", "sequence", "name", "color", "budget", "category", "total_planned", "total_practical"]


@freeze_time("2026-10-15 11:12:13")
class BudgetPositionAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The positions of a budget, nested under it: every route stays within the
    budget of the path. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # On no account, so free in both budgets.
        cls.category_lembas = AccountCategory.objects.create(name="Lembas", color=9)

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/"
        cls.url_detail = f"{cls.url}{POSITION_BREAKFAST_ID}/"
        cls.payload_create = {"sequence": 3, "category": str(cls.category_lembas.pk)}
        cls.payload_update = {"sequence": 7, "category": str(cls.category_lembas.pk)}

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        # The budget of the path only, by sequence.
        self.assertEqual([item["id"] for item in data["results"]], [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID])
        self.assertEqual(data["count"], 2)

        for item in data["results"]:
            self.assert_api_format(item, BudgetPosition.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"name": "break"}, [POSITION_BREAKFAST_ID]),  # the name of the category
            ({"name": "PIPE"}, [POSITION_PIPEWEED_ID]),  # case insensitive
            ({"name": "e"}, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            # A filter cannot reach outside the budget of the path.
            ({"name": "ale"}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, BudgetPosition.objects.get(id=item["id"]))

    # No `test_list_invalid_filters`: the only filter, `name`, is a string, so no
    # value can fail to parse.

    @parameterized.expand(
        [
            ([], ["sequence", "id"]),  # default
            (["sequence"], ["sequence", "id"]),
            (["-sequence"], ["-sequence", "id"]),
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["total_planned"], ["total_planned", "id"]),
            (["-total_planned"], ["-total_planned", "id"]),
            (["total_practical"], ["total_practical", "id"]),
            (["-total_practical"], ["-total_practical", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(BudgetPosition.objects.filter(budget_id=BUDGET_ID1).order_by(*order_by).values_list("pk", flat=True)),
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], POSITION_FIELDS, 7),  # default means all fields: the budget and the category prefetched
            (["budget"], ["id", "budget"], 6),
            (["category"], ["id", "category"], 6),
            (["name", "total_planned"], ["id", "name", "total_planned"], 5),
            (["id"], ["id"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], 2)
        for item in data["results"]:
            self.assert_api_format(item, BudgetPosition.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "budget"],),  # with a relation
            (["not_existing_field", "name"],),
            (["lines"],),  # a relation of the model the schema does not publish
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    # No `test_list_searching`: `BudgetPositionFilterSchema` has no `search`.

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.read"], 200),
            (["totem.budget.create", "totem.budget.update", "totem.budget.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_list_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

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
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID1, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            ([], BUDGET_ID2, [POSITION_ALE_ID]),
            (["budget_position_manage_own"], BUDGET_ID1, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            # Gollum's budget: empty, not an error.
            (["budget_position_manage_own"], BUDGET_ID2, []),
            (["budget_position_manage_all"], BUDGET_ID2, [POSITION_ALE_ID]),
            # The rules of one role combine with AND.
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, []),
        ]
    )
    def test_list_user_access_rules(self, rules, budget_id, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"/api/v1/accounting/budget/{budget_id}/positions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ([], BUDGET_ID2, [POSITION_ALE_ID]),
            (["budget_position_manage_own"], BUDGET_ID1, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            (["budget_position_manage_own"], BUDGET_ID2, [POSITION_ALE_ID]),
            (["budget_position_manage_all"], BUDGET_ID2, [POSITION_ALE_ID]),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, [POSITION_ALE_ID]),
        ]
    )
    def test_list_apikey_access_rules(self, rules, budget_id, expected_pks):
        # A key has no user, hence no role: whatever the rules of the roles, it
        # reads the positions of every budget. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"/api/v1/accounting/budget/{budget_id}/positions/", auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(expected_pks))

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID))
        # Planned from its line, practical from the movements of its category.
        self.assertEqual((data["total_planned"], data["total_practical"]), ("-1000.00", "-80.00"))

    @parameterized.expand(
        [
            ("unknown", f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/{POSITION_ID4}/"),
            # A position of another budget is not found under this one.
            ("another budget's", f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/{POSITION_ALE_ID}/"),
            ("unknown budget", f"/api/v1/accounting/budget/{BUDGET_ID3}/positions/{POSITION_BREAKFAST_ID}/"),
        ]
    )
    def test_retrieve_not_found(self, dummy, url):
        response = self.do_request("GET", url)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.read"], 200),
            (["totem.budget.create", "totem.budget.update", "totem.budget.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_retrieve_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_detail)

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
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID2, POSITION_ALE_ID, 200),
            (["budget_position_manage_own"], BUDGET_ID1, POSITION_BREAKFAST_ID, 200),
            (["budget_position_manage_own"], BUDGET_ID2, POSITION_ALE_ID, 404),  # out of reach reads as missing
            (["budget_position_manage_all"], BUDGET_ID2, POSITION_ALE_ID, 200),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, POSITION_ALE_ID, 404),
        ]
    )
    def test_retrieve_user_access_rules(self, rules, budget_id, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"/api/v1/accounting/budget/{budget_id}/positions/{pk}/")

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["id"], pk)

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_retrieve_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "GET", f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/{POSITION_ALE_ID}/", auth="apikey"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], POSITION_ALE_ID)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 201, None),
            ({"sequence": None}, 422, "sequence"),
            ({"category": None}, 422, "category"),
            # Already a position of the budget: the unique constraint, unkeyed.
            ({"category": CATEGORY_GENERAL_ID}, 422, None),
            ({"category": CATEGORY_SHIRE_ID}, 422, None),
            # A category of another account than the budget's.
            ({"category": CATEGORY_BREE_ID}, 422, "category"),
            ({"category": "01JC0000000000000000000099"}, 422, "category"),  # unknown
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        obj = BudgetPosition.objects.get(id=data["id"])
        self.assert_api_format(data, obj)
        # Filed under the budget of the path; named and colored after its category.
        self.assertEqual((obj.budget_id, data["name"], data["color"]), (BUDGET_ID1, "Lembas", 9))

    def test_create_ignores_a_budget_in_the_body(self):
        response = self.do_request("POST", self.url, data={**self.payload_create, "budget": BUDGET_ID2})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetPosition.objects.get(pk=response.json()["id"]).budget_id, BUDGET_ID1)

    def test_create_under_an_unknown_budget(self):
        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{BUDGET_ID3}/positions/", data=self.payload_create
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], ["budget"])

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.create"], 201),
            (["totem.budget.read", "totem.budget.update", "totem.budget.delete"], 403),
            (["totem.account.create"], 403),
        ]
    )
    def test_create_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.create"], 201),
            (["totem.budget.read", "totem.budget.update", "totem.budget.delete"], 403),
            (["totem.account.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID2, 201),
            (["budget_position_manage_own"], BUDGET_ID1, 201),
            # Out of reach, the created row is refused as a whole: a 403, not the
            # 404 a read would give.
            (["budget_position_manage_own"], BUDGET_ID2, 403),
            (["budget_position_manage_all"], BUDGET_ID2, 201),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, 403),
        ]
    )
    def test_create_user_access_rules(self, rules, budget_id, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{budget_id}/positions/", data=self.payload_create
        )

        self.assertEqual(response.status_code, status_code)
        created = BudgetPosition.objects.filter(budget_id=budget_id, category=self.category_lembas)
        self.assertEqual(created.exists(), status_code == 201)
        if status_code == 201:
            self.assertEqual(response.json()["id"], created.get().pk)
        else:
            self.assertEqual(
                response.json(), {"detail": ["You do not have permission to create some of the objects."]}
            )

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_create_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/", auth="apikey", data=self.payload_create
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.json()["id"], BudgetPosition.objects.get(budget_id=BUDGET_ID2, category=self.category_lembas).pk
        )

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 200),
            ({"sequence": None}, 422),
            ({"category": None}, 422),
            ({"category": CATEGORY_BREE_ID}, 422),  # another account's
            ({"category": CATEGORY_SHIRE_ID}, 422),  # already a position of the budget
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422 and next(iter(extra_body)) == "sequence":
            self.assertIn("sequence", str(response.json()))

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID))
        # The category changed: so do the name, the color and the practical amount.
        self.assertEqual((data["name"], data["color"], data["total_practical"]), ("Lembas", 9, "0.00"))

    def test_update_another_budgets_position(self):
        response = self.do_request("PATCH", f"{self.url}{POSITION_ALE_ID}/", data={"sequence": 1})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_ALE_ID).sequence, 10)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.update"], 200),
            (["totem.budget.create", "totem.budget.read", "totem.budget.delete"], 403),
            (["totem.account.update"], 403),
        ]
    )
    def test_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.update"], 200),
            (["totem.budget.create", "totem.budget.read", "totem.budget.delete"], 403),
            (["totem.account.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID2, POSITION_ALE_ID, 200),
            (["budget_position_manage_own"], BUDGET_ID1, POSITION_BREAKFAST_ID, 200),
            (["budget_position_manage_own"], BUDGET_ID2, POSITION_ALE_ID, 404),
            (["budget_position_manage_all"], BUDGET_ID2, POSITION_ALE_ID, 200),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, POSITION_ALE_ID, 404),
        ]
    )
    def test_update_user_access_rules(self, rules, budget_id, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "PATCH", f"/api/v1/accounting/budget/{budget_id}/positions/{pk}/", data={"sequence": 42}
        )

        self.assertEqual(response.status_code, status_code)
        # Only the position in reach was written.
        self.assertEqual(BudgetPosition.objects.get(pk=pk).sequence == 42, status_code == 200)

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_update_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "PATCH", f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/{POSITION_ALE_ID}/",
            auth="apikey", data={"sequence": 42},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_ALE_ID).sequence, 42)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(BudgetPosition.objects.filter(pk=POSITION_BREAKFAST_ID).exists())
        # Its lines go with it, and the totals of the budget follow.
        self.assertFalse(BudgetLine.objects.filter(position_id=POSITION_BREAKFAST_ID).exists())
        budget = Budget.objects.get(pk=BUDGET_ID1)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount), (Decimal("-300.00"), Decimal("-20.50"))
        )

    def test_delete_another_budgets_position(self):
        response = self.do_request("DELETE", f"{self.url}{POSITION_ALE_ID}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(BudgetPosition.objects.filter(pk=POSITION_ALE_ID).exists())

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.delete"], 204),
            (["totem.budget.create", "totem.budget.read", "totem.budget.update"], 403),
            (["totem.account.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.delete"], 204),
            (["totem.budget.create", "totem.budget.read", "totem.budget.update"], 403),
            (["totem.account.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID2, POSITION_ALE_ID, 204),
            (["budget_position_manage_own"], BUDGET_ID1, POSITION_BREAKFAST_ID, 204),
            (["budget_position_manage_own"], BUDGET_ID2, POSITION_ALE_ID, 404),
            (["budget_position_manage_all"], BUDGET_ID2, POSITION_ALE_ID, 204),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, POSITION_ALE_ID, 404),
        ]
    )
    def test_delete_user_access_rules(self, rules, budget_id, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", f"/api/v1/accounting/budget/{budget_id}/positions/{pk}/")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(BudgetPosition.objects.filter(pk=pk).exists(), status_code != 204)

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_delete_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "DELETE", f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/{POSITION_ALE_ID}/", auth="apikey"
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(BudgetPosition.objects.filter(pk=POSITION_ALE_ID).exists())

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

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or POSITION_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        for name in ("sequence", "name", "color"):
            if name in fields:
                self.assertEqual(api_data[name], getattr(obj, name))
        if "budget" in fields:
            self.assertEqual(api_data["budget"], {"id": obj.budget.pk, "name": obj.budget.name})
        if "category" in fields:
            self.assertEqual(
                api_data["category"],
                {"id": obj.category.pk, "name": obj.category.name, "color": obj.category.color},
            )
        for amount in ("total_planned", "total_practical"):
            if amount in fields:
                # Decimals serialize as strings.
                self.assertEqual(Decimal(api_data[amount]), getattr(obj, amount))

        self.assertEqual(set(fields), set(api_data))
