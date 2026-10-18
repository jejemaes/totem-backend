import json
from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import BudgetLine
from account.tests.common import (
    BUDGET_ID1,
    BUDGET_ID2,
    LINE_FEES_ID,
    LINE_RENT_ID,
    LINE_STOCK_ID,
    POSITION_FEES_ID,
    POSITION_RENT_ID,
    POSITION_STOCK_ID,
    BudgetTestMixin,
)
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

LINE_ID4 = "01JN0000000000000000000099"

LINE_FIELDS = ["id", "budget", "name", "sequence", "position", "planned_amount"]


@freeze_time("2026-10-15 11:12:13")
class BudgetLineAPITest(BudgetTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/lines/"
        cls.url_detail = f"{cls.url}{LINE_RENT_ID}/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/lines/"
        cls.url_resequence = f"{cls.url}resequence/"
        cls.payload_create = {"name": "Deposit", "sequence": 5, "position": POSITION_RENT_ID, "planned_amount": "-500.00"}
        cls.payload_update = {"name": "Rent (revised)", "sequence": 1, "position": POSITION_STOCK_ID, "planned_amount": "-1100.00"}

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
        self.assertEqual(sorted(item["id"] for item in data["results"]), [LINE_RENT_ID, LINE_STOCK_ID])
        self.assertEqual(data["count"], 2)

        for item in data["results"]:
            self._assert_api_format(item, BudgetLine.objects.get(id=item["id"]), LINE_FIELDS)

    @parameterized.expand(
        [
            ({"name": "rest"}, [LINE_STOCK_ID]),
            ({"position": POSITION_RENT_ID}, [LINE_RENT_ID]),
            ({"position": POSITION_RENT_ID, "name": "rest"}, []),
            # A position of another budget: the path wins, nothing is listed.
            ({"position": POSITION_FEES_ID}, []),
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
            (["name"], ["name", "id"]),
            (["-planned_amount"], ["-planned_amount", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}
        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params=params)

        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(BudgetLine.objects.filter(budget_id=BUDGET_ID1).order_by(*order_by).values_list("pk", flat=True)),
        )

    @parameterized.expand(
        [
            ([], LINE_FIELDS, 6),  # the budget and the position prefetched
            (["budget"], ["id", "budget"], 5),
            (["name", "planned_amount"], ["id", "name", "planned_amount"], 4),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params=params)
            data = response.json()

        self.assertEqual(response.status_code, 200)
        for item in data["results"]:
            self._assert_api_format(item, BudgetLine.objects.get(pk=item["id"]), received_fields)

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

    @parameterized.expand([("BUDGET_USER", 0), ("BUDGET_READER", 1)])
    def test_list_access_rules(self, role, count):
        response = self.do_api_request(self.url_other, "GET", self.token_as(role))

        self.assertEqual((response.status_code, response.json()["count"]), (200, count))

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(self.url_detail, "GET", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(response.json(), BudgetLine.objects.get(pk=LINE_RENT_ID), None)

    @parameterized.expand(
        [
            ("unknown", LINE_ID4),
            ("another budget's", LINE_FEES_ID),
        ]
    )
    def test_retrieve_not_found(self, dummy, line_id):
        response = self.do_api_request(f"{self.url}{line_id}/", "GET", self.user_access_token_frodon.token)

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
            ({"name": None}, 422, "name"),
            ({"position": None}, 422, "position"),
            ({"position": POSITION_FEES_ID}, 422, "position"),  # another budget's
            ({"planned_amount": None}, 422, "planned_amount"),
            ({"planned_amount": "1.001"}, 422, "planned_amount"),
            ({"sequence": None}, 422, "sequence"),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data={**self.payload_create, **extra_body}
        )

        self.assertEqual(response.status_code, status_code)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_response(self):
        response = self.do_api_request(self.url, "POST", self.user_access_token_frodon.token, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        obj = BudgetLine.objects.get(id=data["id"])
        self._assert_api_format(data, obj, LINE_FIELDS)
        self.assertEqual(obj.budget_id, BUDGET_ID1)
        self.assertPositionTotals(POSITION_RENT_ID, "-1500.00", "-80.00")
        self.assertBudgetTotals(BUDGET_ID1, "-1800.00", "-100.50")

    def test_create_ignores_a_budget_in_the_body(self):
        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data={**self.payload_create, "budget": BUDGET_ID2}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetLine.objects.get(pk=response.json()["id"]).budget_id, BUDGET_ID1)

    @parameterized.expand([("BUDGET_USER", 422), ("BUDGET_ADMINISTRATOR", 201)])
    def test_create_access_rules(self, role, status_code):
        response = self.do_api_request(
            self.url_other, "POST", self.token_as(role), data={**self.payload_create, "position": POSITION_FEES_ID}
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
            ({"name": None}, 422),
            ({"position": POSITION_FEES_ID}, 422),  # another budget's
            ({"planned_amount": None}, 422),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data={**self.payload_update, **extra_body}
        )

        self.assertEqual(response.status_code, status_code)

    def test_update_response(self):
        response = self.do_api_request(self.url_detail, "PATCH", self.user_access_token_frodon.token, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(response.json(), BudgetLine.objects.get(pk=LINE_RENT_ID), LINE_FIELDS)
        # Moved to the other position, and changed.
        self.assertPositionTotals(POSITION_RENT_ID, "0", "-80.00")
        self.assertPositionTotals(POSITION_STOCK_ID, "-1400.00", "-20.50")
        self.assertBudgetTotals(BUDGET_ID1, "-1400.00", "-100.50")

    def test_update_another_budgets_line(self):
        response = self.do_api_request(
            f"{self.url}{LINE_FEES_ID}/", "PATCH", self.user_access_token_frodon.token, data={"name": "Mine"}
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
        self.assertBudgetTotals(BUDGET_ID1, "-300.00", "-100.50")

    def test_delete_another_budgets_line(self):
        response = self.do_api_request(f"{self.url}{LINE_FEES_ID}/", "DELETE", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(BudgetLine.objects.filter(pk=LINE_FEES_ID).exists())

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
            data=json.dumps({"ids": [LINE_STOCK_ID, LINE_RENT_ID]}),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content, b"")

    @parameterized.expand(
        [
            ("complete list", {"ids": [LINE_STOCK_ID, LINE_RENT_ID]}, 201, None),
            ("partial list", {"ids": [LINE_STOCK_ID]}, 201, None),
            ("empty list", {"ids": []}, 201, None),
            ("offset 0", {"ids": [LINE_STOCK_ID, LINE_RENT_ID], "offset": 0}, 201, None),
            ("offset", {"ids": [LINE_STOCK_ID, LINE_RENT_ID], "offset": 20}, 201, None),
            ("unknown pk", {"ids": [LINE_STOCK_ID, LINE_ID4]}, 422, "ids"),
            ("not a ulid", {"ids": [LINE_STOCK_ID, "not-a-ulid"]}, 422, "ids"),
            ("repeated pk", {"ids": [LINE_STOCK_ID, LINE_STOCK_ID]}, 422, "ids"),
            ("another budget's", {"ids": [LINE_STOCK_ID, LINE_FEES_ID]}, 422, "ids"),
            ("no ids", {"offset": 0}, 422, "ids"),
            ("negative offset", {"ids": [LINE_STOCK_ID], "offset": -1}, 422, "offset"),
            ("offset not an integer", {"ids": [LINE_STOCK_ID], "offset": "first"}, 422, "offset"),
            # An object: neither a bare list nor anything else.
            ("a bare list", [LINE_STOCK_ID, LINE_RENT_ID], 422, None),
            ("a string", LINE_STOCK_ID, 422, None),
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
            self.assertEqual(self.sequences(), {LINE_RENT_ID: 10, LINE_STOCK_ID: 10, LINE_FEES_ID: 10})

    @parameterized.expand(
        [
            ("reversed", {"ids": [LINE_STOCK_ID, LINE_RENT_ID]}, {LINE_STOCK_ID: 1, LINE_RENT_ID: 2}),
            # Only the records given are numbered.
            ("partial", {"ids": [LINE_STOCK_ID]}, {LINE_STOCK_ID: 1, LINE_RENT_ID: 10}),
            # A page of a list: numbered where it sits in the whole list.
            ("page of a list", {"ids": [LINE_STOCK_ID, LINE_RENT_ID], "offset": 20}, {LINE_STOCK_ID: 21, LINE_RENT_ID: 22}),
        ]
    )
    def test_resequence_request(self, dummy, payload, expected):
        self.do_api_request(self.url_resequence, "POST", self.user_access_token_frodon.token, data=json.dumps(payload))

        # Another budget's position is untouched.
        self.assertEqual(self.sequences(), {**expected, LINE_FEES_ID: 10})

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
            data=json.dumps({"ids": [LINE_STOCK_ID, LINE_RENT_ID]}),
        )

        self.assertEqual(response.status_code, status_code)
        if status_code != 201:
            self.assertEqual(response.json(), {"detail": ["You do not have permission to perform this action."]})

    @parameterized.expand(
        [
            ("BUDGET_USER", BUDGET_ID1, [LINE_STOCK_ID, LINE_RENT_ID], 201),
            # Out of scope, another user's lines read as unknown.
            ("BUDGET_USER", BUDGET_ID2, [LINE_FEES_ID], 422),
            ("BUDGET_ADMINISTRATOR", BUDGET_ID2, [LINE_FEES_ID], 201),
        ]
    )
    def test_resequence_access_rules(self, role, budget_id, pks, status_code):
        before = self.sequences()

        response = self.do_api_request(
            f"/api/v1/accounting/budget/{budget_id}/lines/resequence/", "POST",
            self.token_as(role), data=json.dumps({"ids": pks}),
        )

        self.assertEqual(response.status_code, status_code)
        expected = {**before, **{pk: index + 1 for index, pk in enumerate(pks)}} if status_code == 201 else before
        self.assertEqual(self.sequences(), expected)

    def sequences(self):
        return dict(BudgetLine.objects.values_list("id", "sequence"))

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(self, api_data, obj, fields):
        if not fields:
            fields = LINE_FIELDS
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        for name in ("name", "sequence"):
            if name in fields:
                self.assertEqual(api_data[name], getattr(obj, name))
        if "budget" in fields:
            self.assertEqual(api_data["budget"], {"id": obj.budget.pk, "name": obj.budget.name})
        if "position" in fields:
            self.assertEqual(
                api_data["position"],
                {"id": obj.position.pk, "name": obj.position.name, "color": obj.position.color},
            )
        if "planned_amount" in fields:
            self.assertEqual(Decimal(api_data["planned_amount"]), obj.planned_amount)

        self.assertEqual(set(fields), set(api_data.keys()))
