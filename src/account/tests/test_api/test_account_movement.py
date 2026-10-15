from decimal import Decimal

from django.test import TestCase
from django.utils.dateparse import parse_date, parse_datetime
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Account, AccountMovement
from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    MOVEMENT_ID1,
    MOVEMENT_ID2,
    MOVEMENT_ID3,
    AccountTestMixin,
)
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

MOVEMENT_ID4 = "01JM0000000000000000000099"

MOVEMENT_FIELDS = [
    "id",
    "account",
    "amount",
    "name",
    "description",
    "date",
    "reference",
    "category",
    "create_date",
    "update_date",
]


@freeze_time("2026-10-15 11:12:13")
class AccountMovementAPITest(AccountTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = "/api/v1/accounting/movements/"
        cls.url_detail = f"/api/v1/accounting/movements/{MOVEMENT_ID3}/"
        cls.url_detail_uncategorized = f"/api/v1/accounting/movements/{MOVEMENT_ID1}/"
        cls.payload_create = {
            "account": ACCOUNT_ID2,
            "amount": "-12.30",
            "name": "Bank fee",
            "description": "Monthly fee",
            "date": "2026-10-01",
            "reference": "B-42",
            "category": CATEGORY_BANK_ID,
        }
        cls.payload_update = {
            "amount": "-25.00",
            "name": "More stock",
            "description": "Restock",
            "date": "2026-10-02",
            "reference": "PO-7",
            "category": CATEGORY_GENERAL_ID,
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
            obj = AccountMovement.objects.get(id=item["id"])
            self._assert_api_format(item, obj, MOVEMENT_FIELDS)

    @parameterized.expand(
        [
            ({"account": ACCOUNT_ID1}, [MOVEMENT_ID1, MOVEMENT_ID2, MOVEMENT_ID3]),
            ({"account": ACCOUNT_ID2}, []),
            ({"category": CATEGORY_GENERAL_ID}, [MOVEMENT_ID2]),
            ({"direction": "debit"}, [MOVEMENT_ID2, MOVEMENT_ID3]),
            ({"direction": "credit"}, [MOVEMENT_ID1]),
            ({"date_from": "2026-10-15"}, [MOVEMENT_ID1, MOVEMENT_ID2, MOVEMENT_ID3]),  # inclusive
            ({"date_to": "2026-10-15"}, [MOVEMENT_ID1, MOVEMENT_ID2, MOVEMENT_ID3]),  # inclusive
            ({"date_from": "2026-10-16"}, []),
            ({"date_to": "2026-10-14"}, []),
            ({"search": "inv-0"}, [MOVEMENT_ID1]),  # in the reference
            ({"search": "stock"}, [MOVEMENT_ID3]),  # in the name
            ({"account": ACCOUNT_ID1, "direction": "debit", "category": CATEGORY_SHOP_ID}, [MOVEMENT_ID3]),
        ]
    )
    def test_list_filters(self, filters, ids):
        qs = AccountMovement.objects.filter(pk__in=ids)

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["results"]), len(qs))
        self.assertEqual(data["count"], len(qs))

        for item in data["results"]:
            obj = qs.get(id=item["id"])
            self._assert_api_format(item, obj, MOVEMENT_FIELDS)

    @parameterized.expand(
        [
            ({"direction": "sideways"},),
            ({"date_from": "not a date"},),
            ({"date_to": "2026-10-14T09:30:00Z"},),  # a time of day is no date
        ]
    )
    def test_list_invalid_filters(self, filters):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ([], ["-date", "id"]),  # default: the latest first
            (["amount"], ["amount", "id"]),
            (["-amount"], ["-amount", "id"]),
            (["name"], ["name", "id"]),
            (["date", "-amount"], ["date", "-amount", "id"]),
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
            [str(pk) for pk in AccountMovement.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    @parameterized.expand(
        [
            ([], MOVEMENT_FIELDS, 6),  # default means all fields
            (["amount"], ["id", "amount"], 4),
            (["account"], ["id", "account"], 5),
            (["category"], ["id", "category"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        # One prefetch per relation asked for, whatever the number of movements.
        with self.assertNumQueries(query_count):
            response = self.do_api_request(
                self.url, "GET", self.user_access_token_frodon.token, params=params
            )
            data = response.json()

        self.assertEqual(response.status_code, 200)
        for item in data["results"]:
            obj = AccountMovement.objects.get(pk=item["id"])
            self._assert_api_format(item, obj, received_fields)

    @parameterized.expand(
        [
            ("totem.accountmovement.create", 403),
            ("totem.accountmovement.read", 200),
            ("totem.accountmovement.update", 403),
            ("totem.accountmovement.delete", 403),
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

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, self.movement_stock, None)

    def test_retrieve_response_uncategorized(self):
        # The relation unset: `category` is null, and still in the response.
        response = self.do_api_request(
            self.url_detail_uncategorized, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, self.movement_sale, None)
        self.assertIsNone(data["category"])

    def test_retrieve_not_found(self):
        response = self.do_api_request(
            f"{self.url}{MOVEMENT_ID4}/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.accountmovement.read", 200),
            ("totem.accountmovement.create", 403),
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
            ({"account": None}, 422, "account"),
            ({"account": "01JA0000000000000000000099"}, 422, "account"),
            ({"amount": None}, 422, "amount"),
            ({"amount": "0"}, 422, "amount"),
            ({"amount": "1.234"}, 422, "amount"),
            ({"amount": "100"}, 201, None),
            ({"name": None}, 422, "name"),
            ({"date": None}, 422, "date"),
            ({"date": "2026-10-16"}, 422, "date"),  # in the future
            ({"date": "2026-10-15"}, 201, None),  # today
            ({"date": "2026-10-01T09:30:00Z"}, 422, "date"),  # a datetime
            ({"description": None, "reference": None, "category": None}, 201, None),
            ({"category": CATEGORY_GENERAL_ID}, 201, None),
            ({"category": CATEGORY_SHOP_ID}, 422, "category"),  # another account's
            ({"category": "01JC0000000000000000000099"}, 422, "category"),
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
            self.url,
            "POST",
            self.user_access_token_frodon.token,
            data=self.payload_create,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)

        obj = AccountMovement.objects.get(id=data["id"])
        self._assert_api_format(data, obj, MOVEMENT_FIELDS)
        self.assertEqual(data["amount"], "-12.30")

    def test_create_refreshes_the_account(self):
        self.do_api_request(
            self.url,
            "POST",
            self.user_access_token_frodon.token,
            data=self.payload_create,
        )

        response = self.do_api_request(
            f"/api/v1/accounting/accounts/{ACCOUNT_ID2}/", "GET", self.user_access_token_frodon.token
        )
        data = response.json()
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("-12.30", "0.00", "-12.30"),
        )

    @parameterized.expand(
        [
            ("totem.accountmovement.create", 201),
            ("totem.accountmovement.read", 403),
            ("totem.accountmovement.update", 403),
            ("totem.accountmovement.delete", 403),
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
            ({"amount": None}, 422, "amount"),
            ({"amount": "0"}, 422, "amount"),
            ({"name": None}, 422, "name"),
            ({"date": None}, 422, "date"),
            ({"date": "2026-10-16"}, 422, "date"),
            ({"category": None}, 200, None),
            ({"category": CATEGORY_SHOP_ID}, 200, None),  # its own account's
            ({"category": CATEGORY_BANK_ID}, 422, "category"),  # another account's
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        data = {**self.payload_update, **extra_body}

        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data=data
        )

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual(
                [detail["loc"][-1] for detail in response.json()["detail"]], [error_field]
            )

    def test_update_response(self):
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)

        obj = AccountMovement.objects.get(id=MOVEMENT_ID3)
        self._assert_api_format(data, obj, MOVEMENT_FIELDS)
        self.assertEqual(data["amount"], "-25.00")
        # -80.00 - 25.00 replaces -80.00 - 20.50
        account = Account.objects.get(pk=ACCOUNT_ID1)
        self.assertEqual((account.total_debit, account.balance), (Decimal("-105.00"), Decimal("45.00")))

    def test_update_ignores_the_account(self):
        # Not in the update schema: a movement does not change account.
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data={"account": ACCOUNT_ID2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccountMovement.objects.get(pk=MOVEMENT_ID3).account_id, ACCOUNT_ID1)

    def test_update_not_found(self):
        response = self.do_api_request(
            f"{self.url}{MOVEMENT_ID4}/",
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.accountmovement.create", 403),
            ("totem.accountmovement.read", 403),
            ("totem.accountmovement.update", 200),
            ("totem.accountmovement.delete", 403),
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
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        account = Account.objects.get(pk=ACCOUNT_ID1)
        self.assertEqual((account.total_debit, account.balance), (Decimal("-80.00"), Decimal("70.00")))

    def test_delete_not_found(self):
        response = self.do_api_request(
            f"{self.url}{MOVEMENT_ID4}/", "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.accountmovement.create", 403),
            ("totem.accountmovement.read", 403),
            ("totem.accountmovement.update", 403),
            ("totem.accountmovement.delete", 204),
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
            data = response.json()
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(self, api_data, obj, fields):
        if not fields:
            fields = MOVEMENT_FIELDS
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "account" in fields:
            self.assertEqual(
                api_data["account"],
                {"id": obj.account.pk, "code": obj.account.code, "name": obj.account.name},
            )
        if "amount" in fields:
            # A string exact to the cent, never a float.
            self.assertEqual(Decimal(api_data["amount"]), obj.amount)
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "description" in fields:
            self.assertEqual(api_data["description"], obj.description)
        if "reference" in fields:
            self.assertEqual(api_data["reference"], obj.reference)
        if "category" in fields:
            if obj.category is None:
                self.assertIsNone(api_data["category"])
            else:
                self.assertEqual(
                    api_data["category"],
                    {"id": obj.category.pk, "name": obj.category.name, "color": obj.category.color},
                )
        if "date" in fields:
            self.assertEqual(parse_date(api_data["date"]), obj.date)
        for date in ("create_date", "update_date"):
            if date in fields:
                self.assertEqual(parse_datetime(api_data[date]), getattr(obj, date))

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
