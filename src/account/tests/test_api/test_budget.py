from decimal import Decimal

from django.test import TestCase
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Budget
from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    BUDGET_ID1,
    BUDGET_ID2,
    USER_ID1,
    USER_ID2,
    BudgetTestMixin,
)
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

BUDGET_ID3 = "01JB0000000000000000000099"

BUDGET_FIELDS = [
    "id",
    "name",
    "user",
    "account",
    "active",
    "note",
    "total_planned_amount",
    "total_practical_amount",
    "uncategorized_movement_count",
    "create_date",
    "update_date",
]


@freeze_time("2026-10-15 11:12:13")
class BudgetAPITest(BudgetTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user_access_token_tintin = cls.create_token(cls.user)

        cls.url = "/api/v1/accounting/budget/"
        cls.url_detail = f"/api/v1/accounting/budget/{BUDGET_ID1}/"
        cls.url_detail_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/"
        cls.payload_create = {
            "name": "Shop 2027",
            "user": USER_ID2,
            "account": ACCOUNT_ID1,
            "active": True,
            "note": "<p>Next year</p>",
        }
        cls.payload_update = {
            "name": "Shop 2026 (revised)",
            "user": USER_ID2,
            "active": False,
            "note": "<p>Revised</p>",
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["count"], 2)

        for item in data["results"]:
            obj = Budget.objects.get(id=item["id"])
            self._assert_api_format(item, obj, BUDGET_FIELDS)

    @parameterized.expand(
        [
            ({"name": "shop"}, [BUDGET_ID1]),
            ({"name": "2026"}, [BUDGET_ID1, BUDGET_ID2]),
            ({"user": USER_ID2}, [BUDGET_ID2]),
            ({"account": ACCOUNT_ID1}, [BUDGET_ID1]),
            ({"account": ACCOUNT_ID2}, [BUDGET_ID2]),
            ({"active": True}, [BUDGET_ID1, BUDGET_ID2]),
            ({"active": False}, []),
        ]
    )
    def test_list_filters(self, filters, ids):
        qs = Budget.objects.filter(pk__in=ids)

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["results"]), len(qs))
        self.assertEqual(data["count"], len(qs))

        for item in data["results"]:
            obj = qs.get(id=item["id"])
            self._assert_api_format(item, obj, BUDGET_FIELDS)

    @parameterized.expand(
        [
            ([], ["name", "id"]),  # default
            (["-name"], ["-name", "id"]),
            (["total_planned_amount"], ["total_planned_amount", "id"]),
            (["-total_practical_amount"], ["-total_practical_amount", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=params
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(Budget.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    def test_list_ordering_by_a_virtual_field(self):
        # No column to order by.
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token,
            params={"ordering": "uncategorized_movement_count"},
        )

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ([], BUDGET_FIELDS, 9),  # default means all fields
            (["name"], ["id", "name"], 4),
            (["total_planned_amount", "total_practical_amount"], ["id", "total_planned_amount", "total_practical_amount"], 4),
            # Virtual: its own three reads, whatever the number of budgets.
            (["uncategorized_movement_count"], ["id", "uncategorized_movement_count"], 7),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_api_request(
                self.url, "GET", self.user_access_token_frodon.token, params=params
            )
            data = response.json()

        self.assertEqual(response.status_code, 200)
        for item in data["results"]:
            obj = Budget.objects.get(pk=item["id"])
            self._assert_api_format(item, obj, received_fields)

    @parameterized.expand(
        [
            ("totem.budget.create", 403),
            ("totem.budget.read", 200),
            ("totem.budget.update", 403),
            ("totem.budget.delete", 403),
            ("totem.account.read", 403),
        ]
    )
    def test_list_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    @parameterized.expand(
        [
            ("BUDGET_USER", [BUDGET_ID1]),
            ("BUDGET_READER", [BUDGET_ID1, BUDGET_ID2]),
            ("BUDGET_ADMINISTRATOR", [BUDGET_ID1, BUDGET_ID2]),
        ]
    )
    def test_list_access_rules(self, role, ids):
        token = self.token_as(role)

        response = self.do_api_request(self.url, "GET", token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(item["id"] for item in response.json()["results"]), ids)

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, Budget.objects.get(pk=BUDGET_ID1), None)
        self.assertEqual(
            (data["total_planned_amount"], data["total_practical_amount"], data["uncategorized_movement_count"]),
            ("-1300.00", "-100.50", 1),
        )

    def test_retrieve_response_without_user(self):
        # The relation unset: `user` is null, and still in the response.
        Budget.objects.filter(pk=BUDGET_ID1).update(user=None)

        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(response.json(), Budget.objects.get(pk=BUDGET_ID1), None)

    def test_retrieve_not_found(self):
        response = self.do_api_request(
            f"{self.url}{BUDGET_ID3}/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("BUDGET_USER", 404),  # out of scope reads as unknown
            ("BUDGET_READER", 200),
        ]
    )
    def test_retrieve_another_users_budget(self, role, status_code):
        token = self.token_as(role)

        response = self.do_api_request(self.url_detail_other, "GET", token)

        self.assertEqual(response.status_code, status_code)

    @parameterized.expand(
        [
            ("totem.budget.read", 200),
            ("totem.budget.create", 403),
        ]
    )
    def test_retrieve_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            ({"account": None}, 422, "account"),
            ({"account": "01JA0000000000000000000099"}, 422, "account"),
            ({"user": None}, 201, None),
            ({"active": None}, 422, "active"),
            ({"note": "<script>alert(1)</script>"}, 422, "note"),
            ({"note": None}, 201, None),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        data = {**self.payload_create, **extra_body}

        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data=data
        )

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual(
                [detail["loc"][-1] for detail in response.json()["detail"]], [error_field]
            )

    def test_create_response(self):
        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data=self.payload_create,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)
        obj = Budget.objects.get(id=data["id"])
        self._assert_api_format(data, obj, BUDGET_FIELDS)
        self.assertEqual(
            (data["total_planned_amount"], data["total_practical_amount"], data["uncategorized_movement_count"]),
            ("0.00", "0.00", 3),
        )

    def test_create_defaults_the_user(self):
        payload = {k: v for k, v in self.payload_create.items() if k != "user"}

        response = self.do_api_request(self.url, "POST", self.user_access_token_tintin.token, data=payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user"]["id"], USER_ID1)

    @parameterized.expand(
        [
            ("for themselves", {}, 201),
            ("for another user", {"user": USER_ID2}, 403),
        ]
    )
    def test_create_access_rules(self, dummy, values, status_code):
        token = self.token_as("BUDGET_USER")
        payload = {k: v for k, v in self.payload_create.items() if k != "user"}

        response = self.do_api_request(
            self.url, "POST", token, data={**payload, **values}
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

        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data=self.payload_create,
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 201:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422),
            ({"active": None}, 422),
            ({"user": None}, 200),
            ({"note": "<script>alert(1)</script>"}, 422),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        data = {**self.payload_update, **extra_body}

        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data=data
        )

        self.assertEqual(response.status_code, status_code)

    def test_update_response(self):
        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, Budget.objects.get(id=BUDGET_ID1), BUDGET_FIELDS)

    def test_update_ignores_the_account(self):
        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data={"account": ACCOUNT_ID2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.objects.get(pk=BUDGET_ID1).account_id, ACCOUNT_ID1)

    @parameterized.expand([("BUDGET_USER", 404), ("BUDGET_ADMINISTRATOR", 200)])
    def test_update_another_users_budget(self, role, status_code):
        token = self.token_as(role)

        response = self.do_api_request(
            self.url_detail_other, "PATCH", token, data={"name": "Mine"}
        )

        self.assertEqual(response.status_code, status_code)

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

        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_api_request(
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Budget.objects.filter(pk=BUDGET_ID1).exists())

    def test_delete_not_found(self):
        response = self.do_api_request(
            f"{self.url}{BUDGET_ID3}/", "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand([("BUDGET_USER", 404), ("BUDGET_ADMINISTRATOR", 204)])
    def test_delete_another_users_budget(self, role, status_code):
        token = self.token_as(role)

        response = self.do_api_request(self.url_detail_other, "DELETE", token)

        self.assertEqual(response.status_code, status_code)

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

        response = self.do_api_request(
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, status_code)
        if status_code != 204:
            self.assertEqual(
                response.json(), {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(self, api_data, obj, fields):
        if not fields:
            fields = BUDGET_FIELDS
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        for name in ("name", "active", "note"):
            if name in fields:
                self.assertEqual(api_data[name], getattr(obj, name))
        if "user" in fields:
            if obj.user is None:
                self.assertIsNone(api_data["user"])
            else:
                self.assertEqual(api_data["user"], {"id": str(obj.user.pk), "login": obj.user.username})
        if "account" in fields:
            self.assertEqual(
                api_data["account"],
                {"id": obj.account.pk, "code": obj.account.code, "name": obj.account.name},
            )
        for amount in ("total_planned_amount", "total_practical_amount"):
            if amount in fields:
                self.assertEqual(Decimal(api_data[amount]), getattr(obj, amount))
        if "uncategorized_movement_count" in fields:
            self.assertEqual(
                api_data["uncategorized_movement_count"],
                Budget.objects.with_computed("uncategorized_movement_count").get(pk=obj.pk).uncategorized_movement_count,
            )
        for date in ("create_date", "update_date"):
            if date in fields:
                self.assertEqual(parse_datetime(api_data[date]), getattr(obj, date))

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
