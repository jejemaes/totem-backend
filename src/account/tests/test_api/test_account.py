from decimal import Decimal

from django.test import TestCase
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Account
from account.tests.common import ACCOUNT_ID1, ACCOUNT_ID2, ACCOUNT_ID3, AccountTestMixin
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

ACCOUNT_ID4 = "01JA0000000000000000000099"

ACCOUNT_FIELDS = [
    "id",
    "code",
    "name",
    "description",
    "active",
    "total_debit",
    "total_credit",
    "balance",
    "create_date",
    "update_date",
]


@freeze_time("2026-10-15 11:12:13")
class AccountAPITest(AccountTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = "/api/v1/accounting/accounts/"
        cls.url_detail = f"/api/v1/accounting/accounts/{ACCOUNT_ID1}/"
        cls.url_detail_empty = f"/api/v1/accounting/accounts/{ACCOUNT_ID2}/"
        cls.payload_create = {
            "code": "SAVINGS",
            "name": "Savings",
            "description": "Rainy days",
            "active": True,
        }
        cls.payload_update = {
            "code": "MAIN-SHOP",
            "name": "Main shop",
            "description": "The first one",
            "active": True,
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
        self.assertEqual(len(data["results"]), 3)
        self.assertEqual(data["count"], 3)

        for item in data["results"]:
            obj = Account.objects.get(id=item["id"])
            self._assert_api_format(item, obj, ACCOUNT_FIELDS)

    @parameterized.expand(
        [
            ({"active": True}, [ACCOUNT_ID1, ACCOUNT_ID2]),
            ({"active": False}, [ACCOUNT_ID3]),
            ({"search": "shop"}, [ACCOUNT_ID1, ACCOUNT_ID3]),  # in the name
            ({"search": "BAN"}, [ACCOUNT_ID2]),  # in the code
            ({"search": "no-match"}, []),
        ]
    )
    def test_list_filters(self, filters, ids):
        qs = Account.objects.filter(pk__in=ids)

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["results"]), len(qs))
        self.assertEqual(data["count"], len(qs))

        for item in data["results"]:
            obj = qs.get(id=item["id"])
            self._assert_api_format(item, obj, ACCOUNT_FIELDS)

    @parameterized.expand(
        [
            ({"active": "invalid boolean"},),
        ]
    )
    def test_list_invalid_filters(self, filters):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ([], ["code", "id"]),  # default
            (["code"], ["code", "id"]),
            (["-code"], ["-code", "id"]),
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["balance"], ["balance", "id"]),
            (["-balance"], ["-balance", "id"]),
            (["total_debit"], ["total_debit", "id"]),
            (["-total_credit"], ["-total_credit", "id"]),
            (["active", "-code"], ["active", "-code", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=params
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in data["results"]],
            [str(pk) for pk in Account.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    @parameterized.expand(
        [
            ([], ACCOUNT_FIELDS),  # default means all fields
            (["code"], ["id", "code"]),
            (["balance"], ["id", "balance"]),
            (["total_debit", "total_credit", "balance"], ["id", "total_debit", "total_credit", "balance"]),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        # Token, roles, count and page: the totals are columns, they cost no
        # query of their own however many accounts are listed.
        with self.assertNumQueries(4):
            response = self.do_api_request(
                self.url, "GET", self.user_access_token_frodon.token, params=params
            )
            data = response.json()

        self.assertEqual(response.status_code, 200)
        for item in data["results"]:
            obj = Account.objects.get(pk=item["id"])
            self._assert_api_format(item, obj, received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "code"],),
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_api_request(
            self.url,
            "GET",
            self.user_access_token_frodon.token,
            params={"fields": ",".join(query_fields)},
        )

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("totem.account.create", 403),
            ("totem.account.read", 200),
            ("totem.account.update", 403),
            ("totem.account.delete", 403),
            ("totem.accountmovement.read", 403),
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

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, Account.objects.get(pk=ACCOUNT_ID1), None)
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("-100.50", "150.00", "49.50"),
        )

    def test_retrieve_response_without_movements(self):
        response = self.do_api_request(
            self.url_detail_empty, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, Account.objects.get(pk=ACCOUNT_ID2), None)
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("0.00", "0.00", "0.00"),
        )

    def test_retrieve_not_found(self):
        response = self.do_api_request(
            f"{self.url}{ACCOUNT_ID4}/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.account.read", 200),
            ("totem.account.create", 403),
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
            ({"code": None}, 422, "code"),
            ({"code": "lower"}, 422, "code"),
            ({"code": "WITH SPACE"}, 422, "code"),
            ({"code": "A" * 51}, 422, "code"),
            ({"code": "SHOP"}, 422, None),  # taken: reported by the database, unkeyed
            ({"name": None}, 422, "name"),
            ({"name": "Shop"}, 422, None),  # taken
            ({"description": None}, 201, None),
            ({"active": None}, 422, "active"),
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

    def test_create_ignores_the_totals(self):
        # Not in the request schema: a client cannot set what the movements decide.
        data = {**self.payload_create, "balance": "1000.00", "total_credit": "1000.00"}

        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data=data
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["balance"], "0.00")

    def test_create_response(self):
        response = self.do_api_request(
            self.url,
            "POST",
            self.user_access_token_frodon.token,
            data=self.payload_create,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)

        obj = Account.objects.get(id=data["id"])
        self._assert_api_format(data, obj, ACCOUNT_FIELDS)
        # Refreshed with the creation: a new account reads zero, never null.
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("0.00", "0.00", "0.00"),
        )

    @parameterized.expand(
        [
            ("totem.account.create", 201),
            ("totem.account.read", 403),
            ("totem.account.update", 403),
            ("totem.account.delete", 403),
        ]
    )
    def test_create_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url,
            "POST",
            self.user_access_token_frodon.token,
            data=self.payload_create,
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
            ({"code": None}, 422),
            ({"code": "lower"}, 422),
            ({"code": "BANK"}, 422),  # taken
            ({"name": None}, 422),
            ({"name": "Bank"}, 422),  # taken
            ({"description": None}, 200),
            ({"active": None}, 422),
            ({"active": False}, 200),
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
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)

        obj = Account.objects.get(id=ACCOUNT_ID1)
        self._assert_api_format(data, obj, ACCOUNT_FIELDS)
        self.assertEqual(data["code"], "MAIN-SHOP")

    def test_update_ignores_the_totals(self):
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data={"balance": "0.00", "total_debit": "0.00"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "49.50")

    def test_update_not_found(self):
        response = self.do_api_request(
            f"{self.url}{ACCOUNT_ID4}/",
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.account.create", 403),
            ("totem.account.read", 403),
            ("totem.account.update", 200),
            ("totem.account.delete", 403),
        ]
    )
    def test_update_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
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
            self.url_detail_empty, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Account.objects.filter(pk=ACCOUNT_ID2).exists())

    def test_delete_account_with_movements(self):
        # Protected by its movements: deactivate it instead.
        response = self.do_api_request(
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 422)
        self.assertTrue(Account.objects.filter(pk=ACCOUNT_ID1).exists())

    def test_delete_not_found(self):
        response = self.do_api_request(
            f"{self.url}{ACCOUNT_ID4}/", "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.account.create", 403),
            ("totem.account.read", 403),
            ("totem.account.update", 403),
            ("totem.account.delete", 204),
        ]
    )
    def test_delete_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail_empty, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, status_code)
        if status_code != 204:
            data = response.json()
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(self, api_data, obj, fields):
        if not fields:
            fields = ACCOUNT_FIELDS
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "code" in fields:
            self.assertEqual(api_data["code"], obj.code)
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "description" in fields:
            self.assertEqual(api_data["description"], obj.description)
        if "active" in fields:
            self.assertEqual(api_data["active"], obj.active)
        # Amounts travel as strings, exact to the cent: never as floats.
        for amount in ("total_debit", "total_credit", "balance"):
            if amount in fields:
                self.assertEqual(Decimal(api_data[amount]), getattr(obj, amount))
        for date in ("create_date", "update_date"):
            if date in fields:
                self.assertEqual(parse_datetime(api_data[date]), getattr(obj, date))

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
