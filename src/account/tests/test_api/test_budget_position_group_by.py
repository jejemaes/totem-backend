import json

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from totem.api import api_v1
from user.access_rights import get_user_scopes

from .common import (
    BUDGET_ID1,
    BUDGET_ID2,
    BUDGET_SCOPES,
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    PERMISSION_DENIED,
    CommonTestMixin,
)


@freeze_time("2026-10-15 11:12:13")
class BudgetPositionGroupByAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `POST /accounting/budget/{budget_id}/positions/group-by/`, by category.

    A budget has one position per category at most, so within the budget of the
    path a group is one position: Second Breakfast (planned -1000.00, practical
    -80.00) and Pipe-weed (-300.00, -20.50) for Bag End, Ale (-60.00, 0.00) for
    the Prancing Pony.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = BUDGET_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = f"/api/v1/accounting/budget/{BUDGET_ID1}/positions/group-by/"
        cls.url_other = f"/api/v1/accounting/budget/{BUDGET_ID2}/positions/group-by/"
        cls.payload = {"group_by_fields": ["category"], "measures": ["count"]}

    # ------------------------------------------
    # Request
    # ------------------------------------------

    @parameterized.expand(
        [
            ("category", ["category"], 200, None),
            ("no dimension", [], 422, ["group_by_fields"]),
            ("unknown dimension", ["budget"], 422, ["group_by_fields", 0]),
            ("not a dimension", ["name"], 422, ["group_by_fields", 0]),
            # Reported by the service, under the name of the body.
            ("repeated dimension", ["category", "category"], 422, ["group_by_fields"]),
        ]
    )
    def test_group_by_request_group_by_fields(self, dummy, group_by_fields, status_code, loc):
        response = self.do_request("POST", self.url, data=json.dumps({**self.payload, "group_by_fields": group_by_fields}))

        self.assertEqual(response.status_code, status_code)
        if loc:
            self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *loc]])

    @parameterized.expand(
        [
            ("count", ["count"], 200, None),
            ("every measure", ["count", "total_planned_sum", "total_planned_avg", "total_practical_sum",
                               "total_practical_avg"], 200, None),
            ("no measure", [], 422, ["measures"]),
            ("a field, not a measure", ["total_planned"], 422, ["measures", 0]),
            ("unknown aggregate", ["total_planned_max"], 422, ["measures", 0]),
        ]
    )
    def test_group_by_request_measures(self, dummy, measures, status_code, loc):
        response = self.do_request("POST", self.url, data=json.dumps({**self.payload, "measures": measures}))

        self.assertEqual(response.status_code, status_code)
        if loc:
            self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *loc]])

    @parameterized.expand(
        [
            ("none", None, 200, 2),
            ("empty", {}, 200, 2),
            ("name", {"name": "pipe"}, 200, 1),
            # The filters of the list: `name` is a string.
            ("name not a string", {"name": ["pipe"]}, 422, None),
            # An unknown key is ignored, as by the list: it cannot widen the budget
            # of the path.
            ("unknown key", {"budget": BUDGET_ID2}, 200, 2),
            # Not an object: refused, rather than read as "no filter" (see
            # `_require_object` in `core.api.controller`).
            ("a string", "pipe", 422, None),
            ("a number", 42, 422, None),
            ("a boolean", True, 422, None),
            ("a list", [{"name": "pipe"}], 422, None),
        ]
    )
    def test_group_by_request_filters(self, dummy, filters, status_code, count):
        response = self.do_request("POST", self.url, data=json.dumps({**self.payload, "filters": filters}))

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["count"], count)
        else:
            self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", "filters"])

    # ------------------------------------------
    # Response
    # ------------------------------------------

    @parameterized.expand(
        [
            # The budget of the path only; the category as the list renders it.
            (BUDGET_ID1, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            (BUDGET_ID2, [CATEGORY_BREE_ID]),
        ]
    )
    def test_group_by_response_group_by_fields(self, budget_id, category_ids):
        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{budget_id}/positions/group-by/", data=json.dumps(self.payload)
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results"})
        self.assertEqual(data["count"], len(category_ids))
        categories = {
            category.pk: category
            for category in (self.category_general, self.category_shire, self.category_bree)
        }
        self.assertEqual(
            data["results"],
            [
                {
                    "category": {"id": pk, "name": categories[pk].name, "color": categories[pk].color},
                    "count": 1,  # one position per category and budget
                }
                for pk in category_ids
            ],
        )

    @parameterized.expand(
        [
            # Only the keys asked; a sum keeps the decimal string of the list, an
            # average is a float.
            (["count"], [{"count": 1}, {"count": 1}]),
            (["total_planned_sum", "total_planned_avg"],
             [{"total_planned_sum": "-1000.00", "total_planned_avg": -1000.0},
              {"total_planned_sum": "-300.00", "total_planned_avg": -300.0}]),
            (["total_practical_sum", "total_practical_avg"],
             [{"total_practical_sum": "-80.00", "total_practical_avg": -80.0},
              {"total_practical_sum": "-20.50", "total_practical_avg": -20.5}]),
        ]
    )
    def test_group_by_response_measures(self, measures, values):
        response = self.do_request("POST", self.url, data=json.dumps({**self.payload, "measures": measures}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [{key: value for key, value in group.items() if key != "category"} for group in response.json()["results"]],
            values,
        )
        self.assertEqual(
            [group["category"]["id"] for group in response.json()["results"]], [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]
        )

    @parameterized.expand(
        [
            ({}, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            ({"name": "pipe"}, [CATEGORY_SHIRE_ID]),
            ({"name": "BREAKFAST"}, [CATEGORY_GENERAL_ID]),
            # The filters narrow the budget of the path, never widen it.
            ({"name": "ale"}, []),
        ]
    )
    def test_group_by_response_filters(self, filters, category_ids):
        response = self.do_request("POST", self.url, data=json.dumps({**self.payload, "filters": filters}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], len(category_ids))
        self.assertEqual([group["category"]["id"] for group in response.json()["results"]], category_ids)

    @parameterized.expand(
        [
            ([], 200, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            (["total_planned_sum"], 200, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            (["-total_planned_sum"], 200, [CATEGORY_SHIRE_ID, CATEGORY_GENERAL_ID]),
            (["-category"], 200, [CATEGORY_SHIRE_ID, CATEGORY_GENERAL_ID]),
            # Only a dimension or a measure of the request can order.
            (["-total_practical_sum"], 422, ["ordering"]),
            (["name"], 422, ["ordering", 0]),
        ]
    )
    def test_group_by_response_ordering(self, ordering, status_code, expected):
        response = self.do_request(
            "POST", self.url,
            data=json.dumps({**self.payload, "measures": ["total_planned_sum"], "ordering": ordering}),
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual([group["category"]["id"] for group in response.json()["results"]], expected)
        else:
            self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *expected]])

    @parameterized.expand(
        [
            # `count` is over every page.
            ({"limit": 1}, 200, [CATEGORY_GENERAL_ID]),
            ({"limit": 1, "offset": 1}, 200, [CATEGORY_SHIRE_ID]),
            ({"limit": 5, "offset": 2}, 200, []),
            ({"limit": 0}, 422, ["limit"]),
            ({"limit": 1001}, 422, ["limit"]),
            ({"offset": -1}, 422, ["offset"]),
            ({"limit": None, "offset": 1}, 422, ["offset"]),
        ]
    )
    def test_group_by_response_pagination(self, pagination, status_code, expected):
        response = self.do_request("POST", self.url, data=json.dumps({**self.payload, **pagination}))

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["count"], 2)
            self.assertEqual([group["category"]["id"] for group in response.json()["results"]], expected)
        else:
            self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *expected]])

    def test_group_by_openapi(self):
        request = api_v1.get_openapi_schema()["components"]["schemas"]["BudgetPositionGroupBySchema"]["properties"]

        # A single value: pydantic documents it as a `const`, not a one-value `enum`.
        self.assertEqual(request["group_by_fields"]["items"]["const"], "category")
        self.assertEqual(
            request["measures"]["items"]["enum"],
            ["count", "total_planned_sum", "total_planned_avg", "total_practical_sum", "total_practical_avg"],
        )
        self.assertIn("filters", request)

    # ------------------------------------------
    # Access
    # ------------------------------------------

    @parameterized.expand(
        [
            ([], 403),
            (["totem.budget.read"], 200),
            (["totem.budget.create", "totem.budget.update", "totem.budget.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_group_by_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=json.dumps(self.payload))

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
    def test_group_by_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=json.dumps(self.payload))

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], BUDGET_ID2, [CATEGORY_BREE_ID]),
            (["budget_position_manage_own"], BUDGET_ID1, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            # Gollum's budget: no group, not an error.
            (["budget_position_manage_own"], BUDGET_ID2, []),
            (["budget_position_manage_all"], BUDGET_ID2, [CATEGORY_BREE_ID]),
            (["budget_position_manage_own", "budget_position_manage_all"], BUDGET_ID2, []),
        ]
    )
    def test_group_by_user_access_rules(self, rules, budget_id, category_ids):
        self.role.rules = rules
        self.role.save()

        response = self.do_request(
            "POST", f"/api/v1/accounting/budget/{budget_id}/positions/group-by/", data=json.dumps(self.payload)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([group["category"]["id"] for group in response.json()["results"]], category_ids)

    @parameterized.expand(
        [
            ([],),
            (["budget_position_manage_own"],),
            (["budget_position_manage_all"],),
        ]
    )
    def test_group_by_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url_other, auth="apikey", data=json.dumps(self.payload))

        self.assertEqual(response.status_code, 200)
        self.assertEqual([group["category"]["id"] for group in response.json()["results"]], [CATEGORY_BREE_ID])

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
