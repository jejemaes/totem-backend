import json
from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountCategory, BudgetLine, BudgetPosition
from account.tests.common import (
    BUDGET_ID1,
    BUDGET_ID2,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    POSITION_FEES_ID,
    POSITION_RENT_ID,
    POSITION_STOCK_ID,
    BudgetTestMixin,
)
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

POSITION_ID4 = "01JP0000000000000000000099"

POSITION_FIELDS = ["id", "sequence", "name", "color", "budget", "category", "total_planned", "total_practical"]


@freeze_time("2026-10-15 11:12:13")
class BudgetPositionAPITest(BudgetTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category_food = AccountCategory.objects.create(name="Food", color=9)

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/"
        cls.url_detail = f"{cls.url}{POSITION_RENT_ID}/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/"
        cls.url_resequence = f"{cls.url}resequence/"
        cls.payload_create = {"sequence": 3, "category": str(cls.category_food.pk)}
        cls.payload_update = {"sequence": 7, "category": str(cls.category_food.pk)}

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        # The budget of the path only, by sequence.
        self.assertEqual([item["id"] for item in data["results"]], [POSITION_RENT_ID, POSITION_STOCK_ID])
        self.assertEqual(data["count"], 2)

        for item in data["results"]:
            self._assert_api_format(item, BudgetPosition.objects.get(id=item["id"]), POSITION_FIELDS)

    @parameterized.expand(
        [
            ({"name": "ren"}, [POSITION_RENT_ID]),
            ({"name": "o"}, [POSITION_STOCK_ID]),
            # A filter cannot reach outside the budget of the path.
            ({"name": "fees"}, []),
        ]
    )
    def test_list_filters(self, filters, ids):
        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(item["id"] for item in data["results"]), ids)
        self.assertEqual(data["count"], len(ids))

    @parameterized.expand(
        [
            ([], ["sequence", "id"]),  # default
            (["-sequence"], ["-sequence", "id"]),
            (["name"], ["name", "id"]),
            (["total_planned"], ["total_planned", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}
        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params=params)

        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(BudgetPosition.objects.filter(budget_id=BUDGET_ID1).order_by(*order_by).values_list("pk", flat=True)),
        )

    @parameterized.expand(
        [
            ([], POSITION_FIELDS, 6),  # default means all fields: the budget and category prefetched
            (["budget"], ["id", "budget"], 5),
            (["name", "total_planned"], ["id", "name", "total_planned"], 4),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params=params)
            data = response.json()

        self.assertEqual(response.status_code, 200)
        for item in data["results"]:
            self._assert_api_format(item, BudgetPosition.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            ("totem.budget.create", 403),
            ("totem.budget.read", 200),
            ("totem.budget.update", 403),
            ("totem.budget.delete", 403),
        ]
    )
    def test_list_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(response.json(), {"detail": ["You do not have permission to perform this action."]})

    @parameterized.expand(
        [
            ("BUDGET_USER", 0),  # another user's budget: empty
            ("BUDGET_READER", 1),
        ]
    )
    def test_list_access_rules(self, role, count):
        response = self.do_api_request(self.url_other, "GET", self.token_as(role))

        self.assertEqual((response.status_code, response.json()["count"]), (200, count))

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(self.url_detail, "GET", self.user_access_token_frodon.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, BudgetPosition.objects.get(pk=POSITION_RENT_ID), None)
        self.assertEqual((data["total_planned"], data["total_practical"]), ("-1000.00", "-80.00"))

    @parameterized.expand(
        [
            ("unknown", f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/{POSITION_ID4}/"),
            # A position of another budget is not found under this one.
            ("another budget's", f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/{POSITION_FEES_ID}/"),
        ]
    )
    def test_retrieve_not_found(self, dummy, url):
        response = self.do_api_request(url, "GET", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand([("totem.budget.read", 200), ("totem.budget.create", 403)])
    def test_retrieve_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(self.url_detail, "GET", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"category": None}, 422, "category"),
            ({"category": CATEGORY_GENERAL_ID}, 422, None),  # taken in the budget: unkeyed
            ({"category": CATEGORY_BANK_ID}, 422, "category"),  # another account's
            ({"category": CATEGORY_SHOP_ID}, 422, None),  # taken
            ({"sequence": None}, 422, "sequence"),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data={**self.payload_create, **extra_body}
        )

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_response(self):
        response = self.do_api_request(self.url, "POST", self.user_access_token_frodon.token, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        obj = BudgetPosition.objects.get(id=data["id"])
        self._assert_api_format(data, obj, POSITION_FIELDS)
        self.assertEqual((obj.budget_id, data["name"], data["color"]), (BUDGET_ID1, "Food", 9))

    def test_create_ignores_a_budget_in_the_body(self):
        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data={**self.payload_create, "budget": BUDGET_ID2}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetPosition.objects.get(pk=response.json()["id"]).budget_id, BUDGET_ID1)

    def test_create_under_an_unknown_budget(self):
        response = self.do_api_request(
            "/api/v1/accounting/budget/01JB0000000000000000000099/positions/", "POST",
            self.user_access_token_frodon.token, data=self.payload_create,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], ["budget"])

    @parameterized.expand([("BUDGET_USER", 422), ("BUDGET_ADMINISTRATOR", 201)])
    def test_create_access_rules(self, role, status_code):
        # Out of scope, the budget of the path reads as unknown.
        response = self.do_api_request(
            self.url_other, "POST", self.token_as(role), data={"category": str(self.category_food.pk)}
        )

        self.assertEqual(response.status_code, status_code)

    @parameterized.expand(
        [
            ("totem.budget.create", 201),
            ("totem.budget.read", 403),
            ("totem.budget.update", 403),
            ("totem.budget.delete", 403),
        ]
    )
    def test_create_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(self.url, "POST", self.user_access_token_frodon.token, data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code != 201:
            self.assertEqual(response.json(), {"detail": ["You do not have permission to perform this action."]})

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"category": None}, 422),
            ({"category": CATEGORY_BANK_ID}, 422),
            ({"sequence": None}, 422),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data={**self.payload_update, **extra_body}
        )

        self.assertEqual(response.status_code, status_code)

    def test_update_response(self):
        response = self.do_api_request(self.url_detail, "PATCH", self.user_access_token_frodon.token, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, BudgetPosition.objects.get(pk=POSITION_RENT_ID), POSITION_FIELDS)
        # The category changed: so do the name, the color and the practical amount.
        self.assertEqual((data["name"], data["color"], data["total_practical"]), ("Food", 9, "0.00"))

    def test_update_another_budgets_position(self):
        response = self.do_api_request(
            f"{self.url}{POSITION_FEES_ID}/", "PATCH", self.user_access_token_frodon.token, data={"sequence": 1}
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.budget.create", 403),
            ("totem.budget.read", 403),
            ("totem.budget.update", 200),
            ("totem.budget.delete", 403),
        ]
    )
    def test_update_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(self.url_detail, "PATCH", self.user_access_token_frodon.token, data=self.payload_update)

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_api_request(self.url_detail, "DELETE", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(BudgetLine.objects.filter(position_id=POSITION_RENT_ID).exists())
        self.assertBudgetTotals(BUDGET_ID1, "-300.00", "-20.50")

    def test_delete_another_budgets_position(self):
        response = self.do_api_request(f"{self.url}{POSITION_FEES_ID}/", "DELETE", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(BudgetPosition.objects.filter(pk=POSITION_FEES_ID).exists())

    @parameterized.expand(
        [
            ("totem.budget.create", 403),
            ("totem.budget.read", 403),
            ("totem.budget.update", 403),
            ("totem.budget.delete", 204),
        ]
    )
    def test_delete_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(self.url_detail, "DELETE", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Resequence Operation
    # ------------------------------------------

    def test_resequence_response(self):
        response = self.do_api_request(
            self.url_resequence, "POST", self.user_access_token_frodon.token,
            data=json.dumps({"ids": [POSITION_STOCK_ID, POSITION_RENT_ID]}),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content, b"")

    @parameterized.expand(
        [
            ("complete list", {"ids": [POSITION_STOCK_ID, POSITION_RENT_ID]}, 201, None),
            ("partial list", {"ids": [POSITION_STOCK_ID]}, 201, None),
            ("empty list", {"ids": []}, 201, None),
            ("offset 0", {"ids": [POSITION_STOCK_ID, POSITION_RENT_ID], "offset": 0}, 201, None),
            ("offset", {"ids": [POSITION_STOCK_ID, POSITION_RENT_ID], "offset": 20}, 201, None),
            ("unknown pk", {"ids": [POSITION_STOCK_ID, POSITION_ID4]}, 422, "ids"),
            ("not a ulid", {"ids": [POSITION_STOCK_ID, "not-a-ulid"]}, 422, "ids"),
            ("repeated pk", {"ids": [POSITION_STOCK_ID, POSITION_STOCK_ID]}, 422, "ids"),
            ("another budget's", {"ids": [POSITION_STOCK_ID, POSITION_FEES_ID]}, 422, "ids"),
            ("no ids", {"offset": 0}, 422, "ids"),
            ("negative offset", {"ids": [POSITION_STOCK_ID], "offset": -1}, 422, "offset"),
            ("offset not an integer", {"ids": [POSITION_STOCK_ID], "offset": "first"}, 422, "offset"),
            # An object: neither a bare list nor anything else.
            ("a bare list", [POSITION_STOCK_ID, POSITION_RENT_ID], 422, None),
            ("a string", POSITION_STOCK_ID, 422, None),
        ]
    )
    def test_resequence_request_validation(self, dummy, payload, status_code, field):
        response = self.do_api_request(
            self.url_resequence, "POST", self.user_access_token_frodon.token, data=json.dumps(payload)
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            if field:
                self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", field])
            self.assertEqual(self.sequences(), {POSITION_RENT_ID: 1, POSITION_STOCK_ID: 2, POSITION_FEES_ID: 10})

    @parameterized.expand(
        [
            ("reversed", {"ids": [POSITION_STOCK_ID, POSITION_RENT_ID]}, {POSITION_STOCK_ID: 1, POSITION_RENT_ID: 2}),
            # Only the records given are numbered.
            ("partial", {"ids": [POSITION_STOCK_ID]}, {POSITION_STOCK_ID: 1, POSITION_RENT_ID: 1}),
            # A page of a list: numbered where it sits in the whole list.
            ("page of a list", {"ids": [POSITION_STOCK_ID, POSITION_RENT_ID], "offset": 20}, {POSITION_STOCK_ID: 21, POSITION_RENT_ID: 22}),
        ]
    )
    def test_resequence_request(self, dummy, payload, expected):
        self.do_api_request(self.url_resequence, "POST", self.user_access_token_frodon.token, data=json.dumps(payload))

        # Another budget's position is untouched.
        self.assertEqual(self.sequences(), {**expected, POSITION_FEES_ID: 10})

    @parameterized.expand(
        [
            ("totem.budget.update", 201),
            ("totem.budget.read", 403),
            ("totem.budget.create", 403),
            ("totem.budget.delete", 403),
        ]
    )
    def test_resequence_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_resequence, "POST", self.user_access_token_frodon.token,
            data=json.dumps({"ids": [POSITION_STOCK_ID, POSITION_RENT_ID]}),
        )

        self.assertEqual(response.status_code, status_code)
        if status_code != 201:
            self.assertEqual(response.json(), {"detail": ["You do not have permission to perform this action."]})

    @parameterized.expand(
        [
            ("BUDGET_USER", BUDGET_ID1, [POSITION_STOCK_ID, POSITION_RENT_ID], 201),
            # Out of scope, another user's positions read as unknown.
            ("BUDGET_USER", BUDGET_ID2, [POSITION_FEES_ID], 422),
            ("BUDGET_ADMINISTRATOR", BUDGET_ID2, [POSITION_FEES_ID], 201),
        ]
    )
    def test_resequence_access_rules(self, role, budget_id, pks, status_code):
        before = self.sequences()

        response = self.do_api_request(
            f"/api/v1/accounting/budget/{budget_id}/positions/resequence/", "POST",
            self.token_as(role), data=json.dumps({"ids": pks}),
        )

        self.assertEqual(response.status_code, status_code)
        expected = {**before, **{pk: index + 1 for index, pk in enumerate(pks)}} if status_code == 201 else before
        self.assertEqual(self.sequences(), expected)

    def sequences(self):
        return dict(BudgetPosition.objects.values_list("id", "sequence"))

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(self, api_data, obj, fields):
        if not fields:
            fields = POSITION_FIELDS
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
                self.assertEqual(Decimal(api_data[amount]), getattr(obj, amount))

        self.assertEqual(set(fields), set(api_data.keys()))
