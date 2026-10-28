from datetime import date
from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Account, AccountMovement
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from totem.api import api_v1
from user.access_rights import get_user_scopes

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    MOVEMENT_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

MOVEMENT_SEPTEMBER_ALE_ID = "01JM0000000000000000000004"
MOVEMENT_SEPTEMBER_SALE_ID = "01JM0000000000000000000005"
MOVEMENT_SEPTEMBER_BREAKFAST_ID = "01JM0000000000000000000006"

SHIRE = {"id": ACCOUNT_ID1, "code": "SHIRE", "name": "Bag End"}
BREE = {"id": ACCOUNT_ID2, "code": "BREE", "name": "The Prancing Pony"}

# The smallest valid body; each test overrides what it is about.
GROUP_BY_BODY = {"group_by_fields": ["date_month"], "measures": ["count"]}


@freeze_time("2026-10-15 11:12:13")
class AccountMovementGroupByAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `POST /accounting/movements/group-by/`, over a ledger spanning two months
    and two accounts:

        2026-09-03  BREE   -12.30  [Ale]
        2026-09-20  SHIRE  +40.00  -
        2026-09-25  SHIRE  -80.00  [Second Breakfast]
        2026-10-15  SHIRE +150.00  -                    (common)
        2026-10-15  SHIRE  -80.00  [Second Breakfast]   (common)
        2026-10-15  SHIRE  -20.50  [Pipe-weed]          (common)

    No `*_access_rules` tests: no `BaseRule` is registered for `AccountMovement`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        AccountMovement.objects.bulk_create([
            AccountMovement(
                id=MOVEMENT_SEPTEMBER_ALE_ID, account=cls.account_bree, amount=Decimal("-12.30"),
                name="Ale for the Rangers", date=date(2026, 9, 3), category=cls.category_bree,
            ),
            AccountMovement(
                id=MOVEMENT_SEPTEMBER_SALE_ID, account=cls.account_shire, amount=Decimal("40.00"),
                name="Mushrooms sale", date=date(2026, 9, 20),
            ),
            AccountMovement(
                id=MOVEMENT_SEPTEMBER_BREAKFAST_ID, account=cls.account_shire, amount=Decimal("-80.00"),
                name="Second breakfast", date=date(2026, 9, 25), category=cls.category_general,
            ),
        ])
        Account.objects.refresh_computed()

        cls.role.permissions = MOVEMENT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/movements/group-by/"

    # ------------------------------------------
    # Request
    # ------------------------------------------

    @parameterized.expand(
        [
            ("one dimension", ["account"], None),
            ("two dimensions", ["date_month", "category"], None),
            ("three dimensions", ["account", "category", "date_year"], None),
            ("no dimension", [], ["group_by_fields"]),
            ("unknown dimension", ["date"], ["group_by_fields", 0]),
            ("too many dimensions", ["account", "category", "date_month", "date_year"], ["group_by_fields"]),
            # Reported by the service, under the name of the body.
            ("repeated dimension", ["account", "account"], ["group_by_fields"]),
        ]
    )
    def test_group_by_request_group_by_fields(self, dummy, group_by_fields, loc):
        response = self.do_request("POST", self.url, data={**GROUP_BY_BODY, "group_by_fields": group_by_fields})

        if loc is None:
            self.assertEqual(response.status_code, 200)
        else:
            self.assertEqual(response.status_code, 422)
            self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *loc]])

    @parameterized.expand(
        [
            ("count", ["count"], None),
            ("every measure", ["count", "amount_sum", "amount_avg", "amount_min", "amount_max", "debit_sum",
                               "credit_sum", "amount_share"], None),
            ("no measure", [], ["measures"]),
            ("unknown measure", ["amount"], ["measures", 0]),
        ]
    )
    def test_group_by_request_measures(self, dummy, measures, loc):
        response = self.do_request("POST", self.url, data={**GROUP_BY_BODY, "measures": measures})

        if loc is None:
            self.assertEqual(response.status_code, 200)
        else:
            self.assertEqual(response.status_code, 422)
            self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *loc]])

    @parameterized.expand(
        [
            ("no filter", {}, 200),
            ("every filter", {"account": ACCOUNT_ID1, "category": CATEGORY_SHIRE_ID, "direction": "debit",
                              "date_from": "2026-09-01", "date_to": "2026-10-15", "search": "pipe"}, 200),
            ("unknown direction", {"direction": "sideways"}, 422),
            ("not a date", {"date_from": "not a date"}, 422),
            ("a time of day is no date", {"date_to": "2026-10-14T09:30:00Z"}, 422),
            ("null", None, 200),
            # Not an object: refused, rather than read as "no filter".
            ("a string", "pipe", 422),
            ("a number", 42, 422),
            ("a list", [{"direction": "debit"}], 422),
        ]
    )
    def test_group_by_request_filters(self, dummy, filters, status_code):
        response = self.do_request("POST", self.url, data={**GROUP_BY_BODY, "filters": filters})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", "filters"])

    # ------------------------------------------
    # Response
    # ------------------------------------------

    @parameterized.expand(
        [
            # The account as the list renders it, and only the keys asked.
            ("account", ["account"], [
                {"account": SHIRE, "count": 5},
                {"account": BREE, "count": 1},
            ]),
            ("date_month", ["date_month"], [
                {"date_month": "2026-09-01", "count": 3},
                {"date_month": "2026-10-01", "count": 3},
            ]),
            ("date_year", ["date_year"], [
                {"date_year": "2026-01-01", "count": 6},
            ]),
            ("account and date_month", ["account", "date_month"], [
                {"account": SHIRE, "date_month": "2026-09-01", "count": 2},
                {"account": SHIRE, "date_month": "2026-10-01", "count": 3},
                {"account": BREE, "date_month": "2026-09-01", "count": 1},
            ]),
        ]
    )
    def test_group_by_response_group_by_fields(self, dummy, group_by_fields, results):
        response = self.do_request("POST", self.url, data={"group_by_fields": group_by_fields, "measures": ["count"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"count": len(results), "results": results})

    def test_group_by_response_group_by_fields_category(self):
        # The category as the list renders it; the uncategorized movements group
        # under a null, last.
        response = self.do_request("POST", self.url, data={"group_by_fields": ["category"], "measures": ["count"]})

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual(
            results[0]["category"],
            {"id": CATEGORY_GENERAL_ID, "name": "Second Breakfast", "color": self.category_general.color},
        )
        self.assertEqual(
            [(group["category"]["name"] if group["category"] else None, group["count"]) for group in results],
            [("Second Breakfast", 2), ("Pipe-weed", 1), ("Ale", 1), (None, 2)],
        )

    @parameterized.expand(
        [
            # Per account, SHIRE then BREE. Amounts are strings exact to the cent;
            # BREE has no credit, a null rather than a zero.
            ("count", [5, 1]),
            ("amount_sum", ["9.50", "-12.30"]),
            # A float, unlike the other amounts: an average is not exact to the cent.
            ("amount_avg", [1.9, -12.3]),
            ("amount_min", ["-80.00", "-12.30"]),
            ("amount_max", ["150.00", "-12.30"]),
            ("debit_sum", ["-180.50", "-12.30"]),
            ("credit_sum", ["190.00", None]),
        ]
    )
    def test_group_by_response_measures(self, measure, values):
        response = self.do_request("POST", self.url, data={"group_by_fields": ["account"], "measures": [measure]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"],
            [{"account": SHIRE, measure: values[0]}, {"account": BREE, measure: values[1]}],
        )

    def test_group_by_response_measures_amount_share(self):
        # The share of each category in the expenses of its month, in percent.
        response = self.do_request("POST", self.url, data={
            "group_by_fields": ["date_month", "category"],
            "measures": ["amount_share"],
            "filters": {"direction": "debit"},
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                (group["date_month"], group["category"]["name"], round(group["amount_share"], 2))
                for group in response.json()["results"]
            ],
            [
                ("2026-09-01", "Second Breakfast", 86.67),
                ("2026-09-01", "Ale", 13.33),
                ("2026-10-01", "Second Breakfast", 79.6),
                ("2026-10-01", "Pipe-weed", 20.4),
            ],
        )

    @parameterized.expand(
        [
            ({}, [("2026-09-01", 3), ("2026-10-01", 3)]),
            ({"account": ACCOUNT_ID2}, [("2026-09-01", 1)]),
            ({"category": CATEGORY_GENERAL_ID}, [("2026-09-01", 1), ("2026-10-01", 1)]),
            ({"direction": "debit"}, [("2026-09-01", 2), ("2026-10-01", 2)]),
            ({"direction": "credit"}, [("2026-09-01", 1), ("2026-10-01", 1)]),
            ({"date_from": "2026-10-01"}, [("2026-10-01", 3)]),  # inclusive
            ({"date_to": "2026-09-20"}, [("2026-09-01", 2)]),  # inclusive
            ({"search": "breakfast"}, [("2026-09-01", 1), ("2026-10-01", 1)]),
            ({"search": "mordor"}, []),
            ({"account": ACCOUNT_ID1, "direction": "debit", "category": CATEGORY_SHIRE_ID}, [("2026-10-01", 1)]),
        ]
    )
    def test_group_by_response_filters(self, filters, groups):
        response = self.do_request("POST", self.url, data={**GROUP_BY_BODY, "filters": filters})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], len(groups))
        self.assertEqual([(group["date_month"], group["count"]) for group in response.json()["results"]], groups)

    @parameterized.expand(
        [
            # Second Breakfast -160 (2), Pipe-weed -20.50 (1), Ale -12.30 (1), none
            # +190 (2). By pk, Second Breakfast < Pipe-weed < Ale, and NULL last
            # whatever the direction.
            ([], 200, ["Second Breakfast", "Pipe-weed", "Ale", None]),
            (["-amount_sum"], 200, [None, "Ale", "Pipe-weed", "Second Breakfast"]),
            (["count", "-category"], 200, ["Ale", "Pipe-weed", "Second Breakfast", None]),
            # Only the dimensions and the measures asked can order the groups.
            (["date"], 422, ["ordering", 0]),
            (["-amount_avg"], 422, ["ordering"]),
        ]
    )
    def test_group_by_response_ordering(self, ordering, status_code, expected):
        response = self.do_request("POST", self.url, data={
            "group_by_fields": ["category"], "measures": ["amount_sum", "count"], "ordering": ordering,
        })

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(
                [group["category"]["name"] if group["category"] else None for group in response.json()["results"]],
                expected,
            )
        else:
            self.assertEqual(
                [error["loc"] for error in response.json()["detail"]], [["body", "request_body", *expected]]
            )

    @parameterized.expand(
        [
            # Four days hold movements; `count` is theirs, whatever the page.
            ({}, 200, ["2026-10-15", "2026-09-25", "2026-09-20", "2026-09-03"]),
            ({"limit": 2}, 200, ["2026-10-15", "2026-09-25"]),
            ({"limit": 2, "offset": 1}, 200, ["2026-09-25", "2026-09-20"]),
            ({"limit": 10, "offset": 3}, 200, ["2026-09-03"]),
            ({"limit": 2, "offset": 4}, 200, []),
            ({"limit": 0}, 422, ["limit"]),
            ({"limit": 1001}, 422, ["limit"]),
            ({"limit": None, "offset": 1}, 422, ["offset"]),
        ]
    )
    def test_group_by_response_pagination(self, page, status_code, expected):
        response = self.do_request("POST", self.url, data={
            "group_by_fields": ["date_day"], "measures": ["count"], "ordering": ["-date_day"], **page,
        })

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["count"], 4)
            self.assertEqual([group["date_day"] for group in response.json()["results"]], expected)
        else:
            self.assertEqual(
                [error["loc"] for error in response.json()["detail"]], [["body", "request_body", *expected]]
            )

    def test_group_by_openapi(self):
        components = api_v1.get_openapi_schema()["components"]["schemas"]

        request = components["AccountMovementGroupBySchema"]["properties"]
        self.assertEqual(
            request["group_by_fields"]["items"]["enum"],
            ["account", "category", "date_day", "date_week", "date_month", "date_quarter", "date_year"],
        )
        self.assertEqual(
            request["measures"]["items"]["enum"],
            ["count", "amount_sum", "amount_avg", "amount_min", "amount_max", "debit_sum", "credit_sum", "amount_share"],
        )
        self.assertIn("filters", request)
        group = components["AccountMovementGroupSchema"]["properties"]
        self.assertEqual(group["date_month"]["title"], "Date (month)")
        self.assertEqual(group["debit_sum"]["title"], "Debits")

    # ------------------------------------------
    # Access Rights
    # ------------------------------------------

    @parameterized.expand(
        [
            ([], 403),
            # A group sums movements the list would show: the read scope.
            (["totem.accountmovement.read"], 200),
            (["totem.accountmovement.create", "totem.accountmovement.update", "totem.accountmovement.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_group_by_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=GROUP_BY_BODY)

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
    def test_group_by_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=GROUP_BY_BODY)

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
