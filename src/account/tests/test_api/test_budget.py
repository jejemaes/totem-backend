from decimal import Decimal

from django.test import TestCase
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Budget
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.tests.test_api.common import USER_ID1, USER_ID2

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    BUDGET_ID1,
    BUDGET_ID2,
    BUDGET_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

BUDGET_ID3 = "01JB0000000000000000000099"  # matches no budget

ALL_BUDGET_IDS = [BUDGET_ID1, BUDGET_ID2]

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
class BudgetAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ Bag End 2026 (BUDGET_ID1) is in charge of Frodon, who acts; the Prancing
    Pony 2026 (BUDGET_ID2) of Gollum. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/budget/"
        cls.url_detail = f"/api/v1/accounting/budget/{BUDGET_ID1}/"
        cls.payload_create = {
            "name": "Bag End 2027",
            "user": USER_ID2,
            "account": ACCOUNT_ID1,
            "active": True,
            "note": "<p>After the Party</p>",
        }
        cls.payload_update = {
            "name": "Bag End 2026 (revised)",
            "user": USER_ID2,
            "active": False,
            "note": "<p>Revised by Sam</p>",
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_BUDGET_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_BUDGET_IDS))

        for item in data["results"]:
            self.assert_api_format(item, Budget.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"name": "bag end"}, [BUDGET_ID1]),
            ({"name": "2026"}, [BUDGET_ID1, BUDGET_ID2]),
            ({"user": USER_ID2}, [BUDGET_ID2]),
            ({"account": ACCOUNT_ID1}, [BUDGET_ID1]),
            ({"account": ACCOUNT_ID2}, [BUDGET_ID2]),
            ({"active": True}, [BUDGET_ID1, BUDGET_ID2]),
            ({"active": False}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, Budget.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"active": "not a boolean"}, 422, "active"),
            # The ids are refused by the schema, not left to fail in the database.
            ({"user": "frodon"}, 422, "user"),
            ({"account": "not-a-ulid"}, 422, "account"),
        ]
    )
    def test_list_invalid_filters(self, filters, status_code, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["name", "id"]),  # default
            (["-name"], ["-name", "id"]),
            (["active"], ["active", "id"]),
            (["create_date"], ["create_date", "id"]),
            (["total_planned_amount"], ["total_planned_amount", "id"]),
            (["-total_practical_amount"], ["-total_practical_amount", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(Budget.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    def test_list_ordering_by_a_virtual_field(self):
        # `uncategorized_movement_count` has no column to order by.
        response = self.do_request("GET", self.url, params={"ordering": "uncategorized_movement_count"})

        self.assertEqual(response.status_code, 422)

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], BUDGET_FIELDS, 10),  # default means all fields
            (["name"], ["id", "name"], 5),  # `id` is always returned
            (
                ["total_planned_amount", "total_practical_amount"],
                ["id", "total_planned_amount", "total_practical_amount"],
                5,
            ),
            # Virtual: its own three reads, whatever the number of budgets.
            (["uncategorized_movement_count"], ["id", "uncategorized_movement_count"], 8),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_BUDGET_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Budget.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "user"],),  # with a relation
            (["not_existing_field", "name"],),
            (["user_id"],),  # the ORM name of a relation is not a public token
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

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
            ([], ALL_BUDGET_IDS),
            (["budget_manage_own"], [BUDGET_ID1]),
            (["budget_manage_all"], ALL_BUDGET_IDS),
            # The rules of one role combine with AND.
            (["budget_manage_own", "budget_manage_all"], [BUDGET_ID1]),
        ]
    )
    def test_list_user_access_rules(self, rules, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ([],),
            (["budget_manage_own"],),
            (["budget_manage_all"],),
            (["budget_manage_own", "budget_manage_all"],),
        ]
    )
    def test_list_apikey_access_rules(self, rules):
        # A key has no user, hence no role: whatever the rules of the roles, it
        # reads every budget of the tenant. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(ALL_BUDGET_IDS))

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Budget.objects.get(pk=BUDGET_ID1))
        # The Mathom sale is the one movement of SHIRE no position covers.
        self.assertEqual(
            (data["total_planned_amount"], data["total_practical_amount"], data["uncategorized_movement_count"]),
            ("-1300.00", "-100.50", 1),
        )

    def test_retrieve_response_without_user(self):
        # The relation unset: `user` is null, and still in the response.
        Budget.objects.filter(pk=BUDGET_ID1).update(user=None)

        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["user"])
        self.assert_api_format(response.json(), Budget.objects.get(pk=BUDGET_ID1))

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{BUDGET_ID3}/")

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
            ([], BUDGET_ID2, 200),
            (["budget_manage_own"], BUDGET_ID1, 200),
            (["budget_manage_own"], BUDGET_ID2, 404),  # out of reach reads as unknown
            (["budget_manage_all"], BUDGET_ID2, 200),
            (["budget_manage_own", "budget_manage_all"], BUDGET_ID2, 404),
        ]
    )
    def test_retrieve_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"{self.url}{pk}/")

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["id"], pk)

    @parameterized.expand(
        [
            ([],),
            (["budget_manage_own"],),
            (["budget_manage_all"],),
        ]
    )
    def test_retrieve_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"{self.url}{BUDGET_ID2}/", auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], BUDGET_ID2)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            ({"account": None}, 422, "account"),
            ({"account": "01JA0000000000000000000099"}, 422, "account"),  # unknown
            ({"user": None}, 201, None),
            ({"user": "frodon"}, 422, "user"),
            ({"active": None}, 422, "active"),
            ({"note": "<script>alert('Sauron')</script>"}, 422, "note"),
            ({"note": None}, 201, None),
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
        self.assert_api_format(data, Budget.objects.get(id=data["id"]))
        # No position yet: every movement of SHIRE is uncategorized.
        self.assertEqual(
            (data["total_planned_amount"], data["total_practical_amount"], data["uncategorized_movement_count"]),
            ("0.00", "0.00", 3),
        )

    def test_create_defaults_the_user(self):
        payload = {key: value for key, value in self.payload_create.items() if key != "user"}

        response = self.do_request("POST", self.url, data=payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["user"]["id"], USER_ID1)

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
            ([], USER_ID2, 201),
            (["budget_manage_own"], USER_ID1, 201),
            # A budget created out of reach is refused, not created and hidden.
            (["budget_manage_own"], USER_ID2, 403),
            (["budget_manage_all"], USER_ID2, 201),
            (["budget_manage_own", "budget_manage_all"], USER_ID2, 403),
        ]
    )
    def test_create_user_access_rules(self, rules, user_id, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url, data={**self.payload_create, "user": user_id})

        self.assertEqual(response.status_code, status_code)
        created = Budget.objects.filter(name="Bag End 2027")
        if status_code == 201:
            self.assertEqual(
                [(pk, str(user)) for pk, user in created.values_list("pk", "user_id")],
                [(response.json()["id"], user_id)],
            )
        else:
            self.assertFalse(created.exists())

    @parameterized.expand(
        [
            ([],),
            (["budget_manage_own"],),
            (["budget_manage_all"],),
        ]
    )
    def test_create_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key, which creates a budget in
        # charge of anyone. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Budget.objects.filter(pk=response.json()["id"], user_id=USER_ID2).exists())

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422),
            ({"active": None}, 422),
            ({"user": None}, 200),
            ({"user": "frodon"}, 422),
            ({"note": "<script>alert('Sauron')</script>"}, 422),
            ({"note": None}, 200),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), Budget.objects.get(id=BUDGET_ID1))
        self.assertEqual(Budget.objects.get(id=BUDGET_ID1).name, "Bag End 2026 (revised)")

    def test_update_ignores_the_account(self):
        # A budget stays on the account it was created on.
        response = self.do_request("PATCH", self.url_detail, data={"account": ACCOUNT_ID2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.objects.get(pk=BUDGET_ID1).account_id, ACCOUNT_ID1)

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
            ([], BUDGET_ID2, 200),
            (["budget_manage_own"], BUDGET_ID1, 200),
            (["budget_manage_own"], BUDGET_ID2, 404),
            (["budget_manage_all"], BUDGET_ID2, 200),
            (["budget_manage_own", "budget_manage_all"], BUDGET_ID2, 404),
        ]
    )
    def test_update_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", f"{self.url}{pk}/", data={"name": "Mordor 2026"})

        self.assertEqual(response.status_code, status_code)
        # Only the budget in reach was written.
        self.assertEqual(Budget.objects.get(pk=pk).name == "Mordor 2026", status_code == 200)

    @parameterized.expand(
        [
            ([],),
            (["budget_manage_own"],),
            (["budget_manage_all"],),
        ]
    )
    def test_update_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", f"{self.url}{BUDGET_ID2}/", auth="apikey", data={"name": "Mordor 2026"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Budget.objects.get(pk=BUDGET_ID2).name, "Mordor 2026")

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Budget.objects.filter(pk=BUDGET_ID1).exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{BUDGET_ID3}/")

        self.assertEqual(response.status_code, 404)

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
            ([], BUDGET_ID2, 204),
            (["budget_manage_own"], BUDGET_ID1, 204),
            (["budget_manage_own"], BUDGET_ID2, 404),
            (["budget_manage_all"], BUDGET_ID2, 204),
            (["budget_manage_own", "budget_manage_all"], BUDGET_ID2, 404),
        ]
    )
    def test_delete_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", f"{self.url}{pk}/")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Budget.objects.filter(pk=pk).exists(), status_code != 204)

    @parameterized.expand(
        [
            ([],),
            (["budget_manage_own"],),
            (["budget_manage_all"],),
        ]
    )
    def test_delete_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", f"{self.url}{BUDGET_ID2}/", auth="apikey")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Budget.objects.filter(pk=BUDGET_ID2).exists())

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
        fields = fields or BUDGET_FIELDS

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
                Budget.objects.with_computed("uncategorized_movement_count")
                .get(pk=obj.pk)
                .uncategorized_movement_count,
            )
        for date_field in ("create_date", "update_date"):
            if date_field in fields:
                self.assertEqual(parse_datetime(api_data[date_field]), getattr(obj, date_field))

        self.assertEqual(set(fields), set(api_data))
