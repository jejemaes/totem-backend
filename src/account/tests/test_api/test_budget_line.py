from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Budget, BudgetLine, BudgetPosition
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    BUDGET_ID1,
    BUDGET_ID2,
    BUDGET_SCOPES,
    LINE_ALE_ID,
    LINE_BREAKFAST_ID,
    LINE_PIPEWEED_ID,
    PERMISSION_DENIED,
    POSITION_ALE_ID,
    POSITION_BREAKFAST_ID,
    POSITION_PIPEWEED_ID,
    CommonTestMixin,
)

LINE_ID4 = "01JN0000000000000000000099"  # matches no line

LINE_FIELDS = ["id", "budget", "name", "sequence", "position", "planned_amount"]

OWN = "budget_line_manage_own"
ALL = "budget_line_manage_all"


@freeze_time("2026-10-15 11:12:13")
class BudgetLineAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The lines of a budget, nested under it: every route stays within the budget
    of the path.

    Frodon is in charge of BUDGET_ID1 (Second breakfast, Pipe-weed), Gollum of
    BUDGET_ID2 (Ale): that split is what `budget_line_manage_own` is tested against.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/lines/"
        cls.url_detail = f"{cls.url}{LINE_BREAKFAST_ID}/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/lines/"
        cls.payload_create = {
            "name": "Elevenses",
            "sequence": 5,
            "position": POSITION_BREAKFAST_ID,
            "planned_amount": "-500.00",
        }
        cls.payload_update = {
            "name": "Second breakfast (revised)",
            "sequence": 1,
            "position": POSITION_PIPEWEED_ID,
            "planned_amount": "-1100.00",
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        # The budget of the path only.
        self.assertEqual(data["count"], 2)
        self.assertEqual({item["id"] for item in data["results"]}, {LINE_BREAKFAST_ID, LINE_PIPEWEED_ID})

        for item in data["results"]:
            self.assert_api_format(item, BudgetLine.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"name": "weed"}, [LINE_PIPEWEED_ID]),
            ({"position": POSITION_BREAKFAST_ID}, [LINE_BREAKFAST_ID]),
            ({"position": POSITION_BREAKFAST_ID, "name": "weed"}, []),
            # A position of another budget: the path wins, nothing is listed.
            ({"position": POSITION_ALE_ID}, []),
            # Nor can a name reach outside the budget of the path.
            ({"name": "ale"}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

    # No `test_list_invalid_filters`: every filter of `BudgetLineFilterSchema` is a
    # string, so no value can fail to parse.

    @parameterized.expand(
        [
            ([], ["sequence", "id"]),  # default
            (["sequence"], ["sequence", "id"]),
            (["-sequence"], ["-sequence", "id"]),
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["planned_amount"], ["planned_amount", "id"]),
            (["-planned_amount"], ["-planned_amount", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(BudgetLine.objects.filter(budget_id=BUDGET_ID1).order_by(*order_by).values_list("pk", flat=True)),
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], LINE_FIELDS, 7),  # default means all fields: the budget and position prefetched
            (["budget"], ["id", "budget"], 6),  # `id` is always returned
            (["name", "planned_amount"], ["id", "name", "planned_amount"], 5),
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
            self.assert_api_format(item, BudgetLine.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "position"],),  # with a relation
            (["not_existing_field", "name"],),
            (["budget_id"],),  # the column of a relation is not a public token
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    # No `test_list_searching`: `BudgetLineFilterSchema` has no `search` field.

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
            ([], BUDGET_ID1, [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID]),
            ([], BUDGET_ID2, [LINE_ALE_ID]),
            ([OWN], BUDGET_ID1, [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID]),
            ([OWN], BUDGET_ID2, []),  # Gollum's budget
            ([ALL], BUDGET_ID2, [LINE_ALE_ID]),
            # The rules of one role combine with AND.
            ([OWN, ALL], BUDGET_ID2, []),
        ]
    )
    def test_list_user_access_rules(self, rules, budget_id, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"/api/v1/accounting/budget/{budget_id}/lines/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ([],),
            ([OWN],),
            ([ALL],),
            ([OWN, ALL],),
        ]
    )
    def test_list_apikey_access_rules(self, rules):
        # A key has no user, hence no role: whatever the rules of the roles, it
        # reads the lines of every budget. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url_other, auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, {LINE_ALE_ID})

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), BudgetLine.objects.get(pk=LINE_BREAKFAST_ID))

    @parameterized.expand(
        [
            ("unknown", LINE_ID4),
            # Within the budget of the path only.
            ("another_budgets", LINE_ALE_ID),
        ]
    )
    def test_retrieve_not_found(self, dummy, line_id):
        response = self.do_request("GET", f"{self.url}{line_id}/")

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
            ([], BUDGET_ID2, LINE_ALE_ID, 200),
            ([OWN], BUDGET_ID1, LINE_BREAKFAST_ID, 200),
            ([OWN], BUDGET_ID2, LINE_ALE_ID, 404),  # out of reach reads as missing
            ([ALL], BUDGET_ID2, LINE_ALE_ID, 200),
            ([OWN, ALL], BUDGET_ID2, LINE_ALE_ID, 404),
        ]
    )
    def test_retrieve_user_access_rules(self, rules, budget_id, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"/api/v1/accounting/budget/{budget_id}/lines/{pk}/")

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["id"], pk)

    @parameterized.expand(
        [
            ([],),
            ([OWN],),
            ([ALL],),
        ]
    )
    def test_retrieve_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"{self.url_other}{LINE_ALE_ID}/", auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], LINE_ALE_ID)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            ({"position": None}, 422, "position"),
            ({"position": POSITION_ALE_ID}, 422, "position"),  # another budget's
            ({"planned_amount": None}, 422, "planned_amount"),
            ({"planned_amount": "1.001"}, 422, "planned_amount"),
            ({"sequence": None}, 422, "sequence"),
            ({"name": "Elevenses"}, 201, None),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        obj = BudgetLine.objects.get(id=data["id"])
        self.assert_api_format(data, obj)
        self.assertEqual(obj.budget_id, BUDGET_ID1)
        # The totals of the position and of the budget follow.
        position = BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID)
        self.assertEqual((position.total_planned, position.total_practical), (Decimal("-1500.00"), Decimal("-80.00")))
        budget = Budget.objects.get(pk=BUDGET_ID1)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount), (Decimal("-1800.00"), Decimal("-100.50"))
        )

    def test_create_ignores_a_budget_in_the_body(self):
        response = self.do_request("POST", self.url, data={**self.payload_create, "budget": BUDGET_ID2})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetLine.objects.get(pk=response.json()["id"]).budget_id, BUDGET_ID1)

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
            ([], BUDGET_ID2, POSITION_ALE_ID, 201),
            ([OWN], BUDGET_ID1, POSITION_BREAKFAST_ID, 201),
            # Gollum's budget: the position resolves (the role holds no rule on
            # positions), but the line created is out of reach of the line rules,
            # so the whole creation is refused -- a 403, not a 422 nor a 404.
            ([OWN], BUDGET_ID2, POSITION_ALE_ID, 403),
            ([ALL], BUDGET_ID2, POSITION_ALE_ID, 201),
            ([OWN, ALL], BUDGET_ID2, POSITION_ALE_ID, 403),
        ]
    )
    def test_create_user_access_rules(self, rules, budget_id, position_id, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST",
            f"/api/v1/accounting/budget/{budget_id}/lines/",
            data={**self.payload_create, "position": position_id},
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 201:
            self.assertEqual(BudgetLine.objects.get(pk=response.json()["id"]).budget_id, budget_id)
        else:
            self.assertEqual(
                response.json(), {"detail": ["You do not have permission to create some of the objects."]}
            )
            self.assertFalse(BudgetLine.objects.filter(name="Elevenses").exists())

    @parameterized.expand(
        [
            ([],),
            ([OWN],),
            ([ALL],),
        ]
    )
    def test_create_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST", self.url_other, auth="apikey", data={**self.payload_create, "position": POSITION_ALE_ID}
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(BudgetLine.objects.get(pk=response.json()["id"]).budget_id, BUDGET_ID2)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            # Not refused by a validation: the derived `budget` comes out null and
            # the database constraint answers, its SQL message in the response.
            # Pinned as found; it reads like a missing null check on `position`.
            ({"position": None}, 422, "__all__"),
            ({"position": POSITION_ALE_ID}, 422, "position"),  # another budget's
            ({"planned_amount": None}, 422, "planned_amount"),
            ({"planned_amount": "1.001"}, 422, "planned_amount"),
            ({"name": "Second breakfast"}, 200, None),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), BudgetLine.objects.get(pk=LINE_BREAKFAST_ID))
        # Moved to the other position, and changed: both positions follow.
        position = BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID)
        self.assertEqual((position.total_planned, position.total_practical), (Decimal("0"), Decimal("-80.00")))
        position = BudgetPosition.objects.get(pk=POSITION_PIPEWEED_ID)
        self.assertEqual((position.total_planned, position.total_practical), (Decimal("-1400.00"), Decimal("-20.50")))
        budget = Budget.objects.get(pk=BUDGET_ID1)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount), (Decimal("-1400.00"), Decimal("-100.50"))
        )

    def test_update_another_budgets_line(self):
        response = self.do_request("PATCH", f"{self.url}{LINE_ALE_ID}/", data={"name": "Mine"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(BudgetLine.objects.get(pk=LINE_ALE_ID).name, "Ale")

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
            ([], BUDGET_ID2, LINE_ALE_ID, 200),
            ([OWN], BUDGET_ID1, LINE_BREAKFAST_ID, 200),
            ([OWN], BUDGET_ID2, LINE_ALE_ID, 404),
            ([ALL], BUDGET_ID2, LINE_ALE_ID, 200),
            ([OWN, ALL], BUDGET_ID2, LINE_ALE_ID, 404),
        ]
    )
    def test_update_user_access_rules(self, rules, budget_id, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "PATCH", f"/api/v1/accounting/budget/{budget_id}/lines/{pk}/", data={"name": "Lembas"}
        )

        self.assertEqual(response.status_code, status_code)
        # Only the record in reach was written.
        self.assertEqual(BudgetLine.objects.get(pk=pk).name == "Lembas", status_code == 200)

    @parameterized.expand(
        [
            ([],),
            ([OWN],),
            ([ALL],),
        ]
    )
    def test_update_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", f"{self.url_other}{LINE_ALE_ID}/", auth="apikey", data={"name": "Lembas"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(BudgetLine.objects.get(pk=LINE_ALE_ID).name, "Lembas")

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(BudgetLine.objects.filter(pk=LINE_BREAKFAST_ID).exists())
        # The budget totals follow.
        budget = Budget.objects.get(pk=BUDGET_ID1)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount), (Decimal("-300.00"), Decimal("-100.50"))
        )

    def test_delete_another_budgets_line(self):
        response = self.do_request("DELETE", f"{self.url}{LINE_ALE_ID}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(BudgetLine.objects.filter(pk=LINE_ALE_ID).exists())

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
            ([], BUDGET_ID2, LINE_ALE_ID, 204),
            ([OWN], BUDGET_ID1, LINE_BREAKFAST_ID, 204),
            ([OWN], BUDGET_ID2, LINE_ALE_ID, 404),
            ([ALL], BUDGET_ID2, LINE_ALE_ID, 204),
            ([OWN, ALL], BUDGET_ID2, LINE_ALE_ID, 404),
        ]
    )
    def test_delete_user_access_rules(self, rules, budget_id, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", f"/api/v1/accounting/budget/{budget_id}/lines/{pk}/")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(BudgetLine.objects.filter(pk=pk).exists(), status_code != 204)

    @parameterized.expand(
        [
            ([],),
            ([OWN],),
            ([ALL],),
        ]
    )
    def test_delete_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", f"{self.url_other}{LINE_ALE_ID}/", auth="apikey")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(BudgetLine.objects.filter(pk=LINE_ALE_ID).exists())

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
        fields = fields or LINE_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "sequence" in fields:
            self.assertEqual(api_data["sequence"], obj.sequence)
        if "budget" in fields:
            self.assertEqual(api_data["budget"], {"id": obj.budget.pk, "name": obj.budget.name})
        if "position" in fields:
            self.assertEqual(
                api_data["position"],
                {"id": obj.position.pk, "name": obj.position.name, "color": obj.position.color},
            )
        if "planned_amount" in fields:
            self.assertEqual(Decimal(api_data["planned_amount"]), obj.planned_amount)

        self.assertEqual(set(fields), set(api_data))
