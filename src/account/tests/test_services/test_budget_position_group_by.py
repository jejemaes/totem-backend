from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.models import Budget, BudgetLine, BudgetPosition
from account.services import BudgetPositionService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account_category import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
)
from account.tests.test_services.common_budget import BUDGET_BAGEND_ID
from account.tests.test_services.common_budget_line import BudgetLineServiceCommonMixin

OWN = ["budget_position_manage_own"]
ALL = ["budget_position_manage_all"]


class BudgetPositionGroupByServiceTest(BudgetLineServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `group_by` over the budgets, and a second budget of SHIRE in charge of
    Frodon, with a Second Breakfast position: a budget has one position per
    category, so only across budgets does a group hold more than one.

        Second Breakfast  Bag End 2026        -1000.00 planned  -80.00 practical
        Second Breakfast  Bag End 2027        -1200.00 planned  -80.00 practical (the same movements)
        Pipe-weed         Bag End 2026         -300.00 planned  -20.50 practical
        Ale               Prancing Pony 2026    -60.00 planned    0.00 practical
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        budget = Budget.objects.create(name="Bag End 2027", account=cls.account_shire, user=cls.user_frodon)
        position = BudgetPosition.objects.create(budget=budget, category=cls.category_general)
        BudgetLine.objects.create(name="Second breakfast", position=position, planned_amount=Decimal("-1200.00"))
        BudgetPosition.objects.refresh_computed()

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetPositionService, user=self.user_frodon)

    # ------------------------------------------
    # Group By
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the number of groups, the groups, then the categories.
            ("by category", ["category"], 4, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID, CATEGORY_BREE_ID]),
        ]
    )
    def test_group_by_dimensions(self, label, dimensions, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            total, rows = async_to_sync(self.service.group_by)(dimensions, ["count"])

        self.assertEqual((total, [row["category"].pk for row in rows]), (len(expected_pks), expected_pks))

    @parameterized.expand(
        [
            (
                "counts and sums",
                ["count", "total_planned_sum", "total_practical_sum"],
                [(2, Decimal("-2200.00"), Decimal("-160.00")), (1, Decimal("-300.00"), Decimal("-20.50")), (1, Decimal("-60.00"), Decimal("0.00"))],
            ),
            # Pinned as found: an average serializes as a float, a sum as a decimal.
            (
                "averages",
                ["total_planned_avg", "total_practical_avg"],
                [(-1100.0, -80.0), (-300.0, -20.5), (-60.0, 0.0)],
            ),
        ]
    )
    def test_group_by_measures(self, label, measures, expected):
        with self.assertNumQueries(4):
            total, rows = async_to_sync(self.service.group_by)(["category"], measures)

        self.assertEqual(total, 3)
        self.assertEqual([tuple(row[name] for name in measures) for row in rows], expected)

    @parameterized.expand(
        [
            # As the nested route does: one budget, one position per group.
            ("one budget", {"budget_id": BUDGET_BAGEND_ID}, 4, [(CATEGORY_GENERAL_ID, Decimal("-1000.00")), (CATEGORY_SHIRE_ID, Decimal("-300.00"))]),
            ("nothing matches", {"total_planned__lt": -5000}, 3, []),
        ]
    )
    def test_group_by_filters(self, label, filters, query_count, expected):
        with self.assertNumQueries(query_count):
            total, rows = async_to_sync(self.service.group_by)(["category"], ["total_planned_sum"], filters=filters)

        self.assertEqual((total, [(row["category"].pk, row["total_planned_sum"]) for row in rows]), (len(expected), expected))

    @parameterized.expand(
        [
            ("by a measure", ["total_planned_sum"], [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID, CATEGORY_BREE_ID]),
            ("by a measure, descending", ["-count", "-total_planned_sum"], [CATEGORY_GENERAL_ID, CATEGORY_BREE_ID, CATEGORY_SHIRE_ID]),
            ("by default, the keys", None, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID, CATEGORY_BREE_ID]),
        ]
    )
    def test_group_by_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(4):
            total, rows = async_to_sync(self.service.group_by)(["category"], ["count", "total_planned_sum"], ordering=ordering)

        self.assertEqual([row["category"].pk for row in rows], expected_pks)

    @parameterized.expand(
        [
            ("a first page", 2, 0, 4, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            ("the last page", 2, 2, 4, [CATEGORY_BREE_ID]),
            # No group on the page: no category to load.
            ("past the end", 2, 3, 3, []),
        ]
    )
    def test_group_by_pagination(self, label, limit, offset, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            total, rows = async_to_sync(self.service.group_by)(["category"], ["count"], limit=limit, offset=offset)

        self.assertEqual((total, [row["category"].pk for row in rows]), (3, expected_pks))

    @parameterized.expand(
        [
            ("unknown dimension", {"dimensions": ["budget"]}, "dimensions"),
            ("unknown measure", {"measures": ["total_planned_max"]}, "measures"),
            ("ordering not asked", {"ordering": ["-total_planned_sum"]}, "ordering"),
            ("offset without limit", {"offset": 1}, "offset"),
        ]
    )
    def test_group_by_invalid(self, label, arguments, key):
        arguments = {"dimensions": ["category"], "measures": ["count"], **arguments}

        with self.assertNumQueries(0):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.group_by)(**arguments)

        self.assertEqual(list(ctx.exception.dict()["__all__"]), [key])

    @parameterized.expand(
        [
            ("no rule", [], [(CATEGORY_GENERAL_ID, 2), (CATEGORY_SHIRE_ID, 1), (CATEGORY_BREE_ID, 1)]),
            # Not the Ale of Gollum's budget.
            ("own positions", OWN, [(CATEGORY_GENERAL_ID, 2), (CATEGORY_SHIRE_ID, 1)]),
            ("all positions", ALL, [(CATEGORY_GENERAL_ID, 2), (CATEGORY_SHIRE_ID, 1), (CATEGORY_BREE_ID, 1)]),
            ("both, combined with AND", OWN + ALL, [(CATEGORY_GENERAL_ID, 2), (CATEGORY_SHIRE_ID, 1)]),
            ("anonymous: no role, no rule", None, [(CATEGORY_GENERAL_ID, 2), (CATEGORY_SHIRE_ID, 1), (CATEGORY_BREE_ID, 1)]),
        ]
    )
    def test_group_by_access_rules(self, label, rules, expected):
        if rules is None:
            service = self.get_service(BudgetPositionService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(BudgetPositionService, user=self.user_frodon)

        # An anonymous caller has no role to read.
        with self.assertNumQueries(3 if rules is None else 4):
            total, rows = async_to_sync(service.group_by)(["category"], ["count"])

        self.assertEqual((total, [(row["category"].pk, row["count"]) for row in rows]), (len(expected), expected))
