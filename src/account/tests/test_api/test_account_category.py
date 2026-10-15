from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountCategory, AccountMovement
from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    ACCOUNT_ID3,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    MOVEMENT_ID3,
    AccountTestMixin,
)
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

CATEGORY_ID4 = "01JC0000000000000000000099"

CATEGORY_FIELDS = ["id", "name", "color", "account"]


@freeze_time("2026-10-15 11:12:13")
class AccountCategoryAPITest(AccountTestMixin, CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = "/api/v1/accounting/categories/"
        cls.url_detail = f"/api/v1/accounting/categories/{CATEGORY_SHOP_ID}/"
        cls.url_detail_general = f"/api/v1/accounting/categories/{CATEGORY_GENERAL_ID}/"
        cls.payload_create = {
            "name": "Supplies",
            "color": 4,
            "account": ACCOUNT_ID1,
        }
        cls.payload_update = {
            "name": "Goods",
            "color": 7,
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
            obj = AccountCategory.objects.get(id=item["id"])
            self._assert_api_format(item, obj, CATEGORY_FIELDS)

    @parameterized.expand(
        [
            ({"account": ACCOUNT_ID1}, [CATEGORY_SHOP_ID]),
            ({"account": ACCOUNT_ID3}, []),
            # What a movement of the account may use: the general ones and its own.
            ({"applicable_to": ACCOUNT_ID1}, [CATEGORY_GENERAL_ID, CATEGORY_SHOP_ID]),
            ({"applicable_to": ACCOUNT_ID2}, [CATEGORY_GENERAL_ID, CATEGORY_BANK_ID]),
            ({"applicable_to": ACCOUNT_ID3}, [CATEGORY_GENERAL_ID]),
            ({"search": "re"}, [CATEGORY_GENERAL_ID]),
            ({"search": "no-match"}, []),
        ]
    )
    def test_list_filters(self, filters, ids):
        qs = AccountCategory.objects.filter(pk__in=ids)

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["results"]), len(qs))
        self.assertEqual(data["count"], len(qs))

        for item in data["results"]:
            obj = qs.get(id=item["id"])
            self._assert_api_format(item, obj, CATEGORY_FIELDS)

    @parameterized.expand(
        [
            ([], ["name", "id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["color"], ["color", "id"]),
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
            [str(pk) for pk in AccountCategory.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    @parameterized.expand(
        [
            ([], CATEGORY_FIELDS, 5),  # default means all fields
            (["name"], ["id", "name"], 4),
            (["account"], ["id", "account"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        # One more query when the account is asked for: its prefetch.
        with self.assertNumQueries(query_count):
            response = self.do_api_request(
                self.url, "GET", self.user_access_token_frodon.token, params=params
            )
            data = response.json()

        self.assertEqual(response.status_code, 200)
        for item in data["results"]:
            obj = AccountCategory.objects.get(pk=item["id"])
            self._assert_api_format(item, obj, received_fields)

    @parameterized.expand(
        [
            ("totem.accountcategory.create", 403),
            ("totem.accountcategory.read", 200),
            ("totem.accountcategory.update", 403),
            ("totem.accountcategory.delete", 403),
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
        self._assert_api_format(data, self.category_shop, None)

    def test_retrieve_response_general(self):
        # The relation unset: `account` is null, and still in the response.
        response = self.do_api_request(
            self.url_detail_general, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, self.category_general, None)
        self.assertIsNone(data["account"])

    def test_retrieve_not_found(self):
        response = self.do_api_request(
            f"{self.url}{CATEGORY_ID4}/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.accountcategory.read", 200),
            ("totem.accountcategory.create", 403),
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
            ({"name": "Stock"}, 422, None),  # taken on that account: unkeyed
            ({"name": "Rent"}, 201, None),  # a general name, reused on an account
            ({"name": "Rent", "account": None}, 422, None),  # taken among the general ones
            ({"color": -1}, 422, "color"),
            ({"color": 16}, 422, "color"),
            ({"color": None}, 422, "color"),
            ({"account": None}, 201, None),
            ({"account": "01JA0000000000000000000099"}, 422, "account"),
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

        obj = AccountCategory.objects.get(id=data["id"])
        self._assert_api_format(data, obj, CATEGORY_FIELDS)

    @parameterized.expand(
        [
            ("totem.accountcategory.create", 201),
            ("totem.accountcategory.read", 403),
            ("totem.accountcategory.update", 403),
            ("totem.accountcategory.delete", 403),
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
            ({"name": None}, 422),
            ({"color": 16}, 422),
            ({"color": None}, 422),
            ({"name": "Rent"}, 200),  # only taken among the general ones
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

        obj = AccountCategory.objects.get(id=CATEGORY_SHOP_ID)
        self._assert_api_format(data, obj, CATEGORY_FIELDS)
        self.assertEqual((data["name"], data["color"]), ("Goods", 7))

    def test_update_ignores_the_account(self):
        # Not in the update schema: the scope of a category is fixed at creation.
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data={"account": ACCOUNT_ID2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccountCategory.objects.get(pk=CATEGORY_SHOP_ID).account_id, ACCOUNT_ID1)

    @parameterized.expand(
        [
            ("totem.accountcategory.create", 403),
            ("totem.accountcategory.read", 403),
            ("totem.accountcategory.update", 200),
            ("totem.accountcategory.delete", 403),
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
        # Its movements stay, uncategorized.
        self.assertIsNone(AccountMovement.objects.get(pk=MOVEMENT_ID3).category_id)

    def test_delete_not_found(self):
        response = self.do_api_request(
            f"{self.url}{CATEGORY_ID4}/", "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("totem.accountcategory.create", 403),
            ("totem.accountcategory.read", 403),
            ("totem.accountcategory.update", 403),
            ("totem.accountcategory.delete", 204),
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
            fields = CATEGORY_FIELDS
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "color" in fields:
            self.assertEqual(api_data["color"], obj.color)
        if "account" in fields:
            if obj.account is None:
                self.assertIsNone(api_data["account"])
            else:
                self.assertEqual(
                    api_data["account"],
                    {"id": obj.account.pk, "code": obj.account.code, "name": obj.account.name},
                )

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
