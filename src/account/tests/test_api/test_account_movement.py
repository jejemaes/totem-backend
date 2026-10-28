from decimal import Decimal

from django.test import TestCase
from django.utils.dateparse import parse_date, parse_datetime
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Account, AccountMovement
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    MOVEMENT_ID1,
    MOVEMENT_ID2,
    MOVEMENT_ID3,
    MOVEMENT_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

MOVEMENT_ID4 = "01JM0000000000000000000099"  # matches no movement

ALL_MOVEMENT_IDS = [MOVEMENT_ID1, MOVEMENT_ID2, MOVEMENT_ID3]

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
class AccountMovementAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for
    `AccountMovement`, whoever holds a scope reaches every movement. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = MOVEMENT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/movements/"
        cls.url_detail = f"/api/v1/accounting/movements/{MOVEMENT_ID3}/"
        cls.url_detail_uncategorized = f"/api/v1/accounting/movements/{MOVEMENT_ID1}/"
        cls.payload_create = {
            "account": ACCOUNT_ID2,
            "amount": "-12.30",
            "name": "Ale for the Rangers",
            "description": "A round for Strider",
            "date": "2026-10-01",
            "reference": "PONY-42",
            "category": CATEGORY_BREE_ID,
        }
        cls.payload_update = {
            "amount": "-25.00",
            "name": "Longbottom Leaf",
            "description": "The finest weed in the Southfarthing",
            "date": "2026-10-02",
            "reference": "TOBY-7",
            "category": CATEGORY_GENERAL_ID,
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_MOVEMENT_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_MOVEMENT_IDS))

        for item in data["results"]:
            self.assert_api_format(item, AccountMovement.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"account": ACCOUNT_ID1}, ALL_MOVEMENT_IDS),
            ({"account": ACCOUNT_ID2}, []),
            ({"category": CATEGORY_GENERAL_ID}, [MOVEMENT_ID2]),
            ({"direction": "debit"}, [MOVEMENT_ID2, MOVEMENT_ID3]),
            ({"direction": "credit"}, [MOVEMENT_ID1]),
            ({"date_from": "2026-10-15"}, ALL_MOVEMENT_IDS),  # inclusive
            ({"date_to": "2026-10-15"}, ALL_MOVEMENT_IDS),  # inclusive
            ({"date_from": "2026-10-16"}, []),
            ({"date_to": "2026-10-14"}, []),
            ({"search": "inv-0"}, [MOVEMENT_ID1]),  # in the reference
            ({"search": "pipe"}, [MOVEMENT_ID3]),  # in the name
            ({"account": ACCOUNT_ID1, "direction": "debit", "category": CATEGORY_SHIRE_ID}, [MOVEMENT_ID3]),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, AccountMovement.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"direction": "sideways"}, "direction"),
            ({"date_from": "not a date"}, "date_from"),
            ({"date_to": "2026-10-14T09:30:00Z"}, "date_to"),  # a time of day is no date
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["-date", "id"]),  # default: the latest first
            (["amount"], ["amount", "id"]),
            (["-amount"], ["-amount", "id"]),
            (["name"], ["name", "id"]),
            (["reference"], ["reference", "id"]),
            (["date", "-amount"], ["date", "-amount", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in AccountMovement.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    # The query counts include the one minting the token reads the roles with,
    # and one prefetch per relation asked for, whatever the number of movements.
    @parameterized.expand(
        [
            ([], MOVEMENT_FIELDS, 7),  # default means all fields
            (["amount"], ["id", "amount"], 5),  # `id` is always returned
            (["account"], ["id", "account"], 6),
            (["category"], ["id", "category"], 6),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_MOVEMENT_IDS))
        for item in data["results"]:
            self.assert_api_format(item, AccountMovement.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "account"],),  # with a relation
            (["not_existing_field", "name"],),
            (["account_id"],),  # the ORM column of a relation is not a public token
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("INV", [MOVEMENT_ID1]),  # the reference, case insensitive
            ("breakfast", [MOVEMENT_ID2]),  # the name
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
            self.assert_api_format(item, AccountMovement.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountmovement.read"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
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
            (["totem.accountmovement.read"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
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

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), self.movement_pipeweed)

    def test_retrieve_response_uncategorized(self):
        # The relation unset: `category` is null, and still in the response.
        response = self.do_request("GET", self.url_detail_uncategorized)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, self.movement_sale)
        self.assertIsNone(data["category"])

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{MOVEMENT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountmovement.read"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
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
            (["totem.accountmovement.read"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
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
            ({"category": CATEGORY_SHIRE_ID}, 422, "category"),  # another account's
            ({"category": "01JC0000000000000000000099"}, 422, "category"),
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
        self.assert_api_format(data, AccountMovement.objects.get(id=data["id"]))
        self.assertEqual(data["amount"], "-12.30")

    def test_create_refreshes_the_account(self):
        self.do_request("POST", self.url, data=self.payload_create)

        account = Account.objects.get(pk=ACCOUNT_ID2)
        self.assertEqual(
            (account.total_debit, account.total_credit, account.balance),
            (Decimal("-12.30"), Decimal("0.00"), Decimal("-12.30")),
        )

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountmovement.create"], 201),
            (["totem.accountmovement.read", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
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
            (["totem.accountmovement.create"], 201),
            (["totem.accountmovement.read", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
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

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"amount": None}, 422, "amount"),
            ({"amount": "0"}, 422, "amount"),
            ({"name": None}, 422, "name"),
            ({"date": None}, 422, "date"),
            ({"date": "2026-10-16"}, 422, "date"),  # in the future
            ({"category": None}, 200, None),
            ({"category": CATEGORY_SHIRE_ID}, 200, None),  # its own account's
            ({"category": CATEGORY_BREE_ID}, 422, "category"),  # another account's
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, AccountMovement.objects.get(id=MOVEMENT_ID3))
        self.assertEqual(data["amount"], "-25.00")
        # -80.00 - 25.00 replaces -80.00 - 20.50
        account = Account.objects.get(pk=ACCOUNT_ID1)
        self.assertEqual((account.total_debit, account.balance), (Decimal("-105.00"), Decimal("45.00")))

    def test_update_ignores_the_account(self):
        # Not in the update schema: a movement does not change account.
        response = self.do_request("PATCH", self.url_detail, data={"account": ACCOUNT_ID2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccountMovement.objects.get(pk=MOVEMENT_ID3).account_id, ACCOUNT_ID1)

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{MOVEMENT_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountmovement.update"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.read", "totem.accountmovement.delete"], 403),
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
            (["totem.accountmovement.update"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.read", "totem.accountmovement.delete"], 403),
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

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(AccountMovement.objects.filter(pk=MOVEMENT_ID3).exists())
        # The account loses the movement from its totals.
        account = Account.objects.get(pk=ACCOUNT_ID1)
        self.assertEqual((account.total_debit, account.balance), (Decimal("-80.00"), Decimal("70.00")))

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{MOVEMENT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountmovement.delete"], 204),
            (["totem.accountmovement.create", "totem.accountmovement.read", "totem.accountmovement.update"], 403),
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
            (["totem.accountmovement.delete"], 204),
            (["totem.accountmovement.create", "totem.accountmovement.read", "totem.accountmovement.update"], 403),
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
        fields = fields or MOVEMENT_FIELDS

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
        for date_field in ("create_date", "update_date"):
            if date_field in fields:
                self.assertEqual(parse_datetime(api_data[date_field]), getattr(obj, date_field))

        self.assertEqual(set(fields), set(api_data))
