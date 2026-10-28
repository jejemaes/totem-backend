from decimal import Decimal

from django.test import TestCase
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Account
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    ACCOUNT_ID3,
    ACCOUNT_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

ACCOUNT_ID4 = "01JA0000000000000000000099"  # matches no account

ALL_ACCOUNT_IDS = [ACCOUNT_ID1, ACCOUNT_ID2, ACCOUNT_ID3]

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
class AccountAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `Account`, so
    whoever holds a scope reaches every account. Add them with the first rule. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = ACCOUNT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/accounts/"
        cls.url_detail = f"{cls.url}{ACCOUNT_ID1}/"  # SHIRE, with movements
        # MORIA: no movement, no category, no budget, so nothing protects it.
        cls.url_detail_empty = f"{cls.url}{ACCOUNT_ID3}/"
        cls.payload_create = {
            "code": "RIVENDELL",
            "name": "The Last Homely House",
            "description": "East of the Sea",
            "active": True,
        }
        cls.payload_update = {
            "code": "BAG-END",
            "name": "Bag End, Hobbiton",
            "description": "Under the Hill",
            "active": True,
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_ACCOUNT_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_ACCOUNT_IDS))

        for item in data["results"]:
            self.assert_api_format(item, Account.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"active": True}, [ACCOUNT_ID1, ACCOUNT_ID2]),
            ({"active": False}, [ACCOUNT_ID3]),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, Account.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"active": "not a boolean"}, "active"),
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

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

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in Account.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    # Mint (roles), user, roles, count and page: the totals are columns, they cost
    # no query of their own however many accounts are listed.
    @parameterized.expand(
        [
            ([], ACCOUNT_FIELDS, 5),  # default means all fields
            (["code"], ["id", "code"], 5),  # `id` is always returned
            (["balance"], ["id", "balance"], 5),
            (["total_debit", "total_credit", "balance"], ["id", "total_debit", "total_credit", "balance"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_ACCOUNT_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Account.objects.get(id=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "code"],),
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("bag", [ACCOUNT_ID1]),  # in the name
            ("BRE", [ACCOUNT_ID2]),  # in the code
            ("dum", [ACCOUNT_ID3]),  # inactive accounts are searched too
            ("a", ALL_ACCOUNT_IDS),
            ("mordor", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, Account.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.read"], 200),
            (["totem.account.create", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountmovement.read"], 403),
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
            (["totem.account.read"], 200),
            (["totem.account.create", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountmovement.read"], 403),
        ]
    )
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Account.objects.get(pk=ACCOUNT_ID1))
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("-100.50", "150.00", "49.50"),
        )

    def test_retrieve_response_without_movements(self):
        response = self.do_request("GET", f"{self.url}{ACCOUNT_ID2}/")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Account.objects.get(pk=ACCOUNT_ID2))
        # Zero, never null.
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("0.00", "0.00", "0.00"),
        )

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{ACCOUNT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.read"], 200),
            (["totem.account.create", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountmovement.read"], 403),
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
            (["totem.account.read"], 200),
            (["totem.account.create", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountmovement.read"], 403),
        ]
    )
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"code": None}, 422, "code"),
            ({"code": "lower"}, 422, "code"),
            ({"code": "WITH SPACE"}, 422, "code"),
            ({"code": "A" * 51}, 422, "code"),
            ({"code": "SHIRE"}, 422, None),  # taken: reported by the database, unkeyed
            ({"name": None}, 422, "name"),
            ({"name": "Bag End"}, 422, None),  # taken
            ({"description": None}, 201, None),
            ({"active": None}, 422, "active"),
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
        self.assert_api_format(data, Account.objects.get(id=data["id"]))
        # Refreshed with the creation: a new account reads zero, never null.
        self.assertEqual(
            (data["total_debit"], data["total_credit"], data["balance"]),
            ("0.00", "0.00", "0.00"),
        )

    def test_create_ignores_the_totals(self):
        # Not in the request schema: a client cannot set what the movements decide.
        data = {**self.payload_create, "balance": "1000.00", "total_credit": "1000.00"}

        response = self.do_request("POST", self.url, data=data)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["balance"], "0.00")

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.create"], 201),
            (["totem.account.read", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountmovement.create"], 403),
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
            (["totem.account.create"], 201),
            (["totem.account.read", "totem.account.update", "totem.account.delete"], 403),
            (["totem.accountmovement.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"code": None}, 422),
            ({"code": "lower"}, 422),
            ({"code": "BREE"}, 422),  # taken
            ({"name": None}, 422),
            ({"name": "The Prancing Pony"}, 422),  # taken
            ({"description": None}, 200),
            ({"active": None}, 422),
            ({"active": False}, 200),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Account.objects.get(id=ACCOUNT_ID1))
        self.assertEqual(data["code"], "BAG-END")

    def test_update_ignores_the_totals(self):
        response = self.do_request("PATCH", self.url_detail, data={"balance": "0.00", "total_debit": "0.00"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "49.50")

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{ACCOUNT_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.update"], 200),
            (["totem.account.create", "totem.account.read", "totem.account.delete"], 403),
            (["totem.accountmovement.update"], 403),
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
            (["totem.account.update"], 200),
            (["totem.account.create", "totem.account.read", "totem.account.delete"], 403),
            (["totem.accountmovement.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail_empty)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Account.objects.filter(pk=ACCOUNT_ID3).exists())

    def test_delete_account_with_movements(self):
        # Protected by its movements: deactivate it instead.
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 422)
        self.assertTrue(Account.objects.filter(pk=ACCOUNT_ID1).exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{ACCOUNT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.delete"], 204),
            (["totem.account.create", "totem.account.read", "totem.account.update"], 403),
            (["totem.accountmovement.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail_empty)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.account.delete"], 204),
            (["totem.account.create", "totem.account.read", "totem.account.update"], 403),
            (["totem.accountmovement.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail_empty, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

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
        fields = fields or ACCOUNT_FIELDS

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

        self.assertEqual(set(fields), set(api_data))
