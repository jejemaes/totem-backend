from datetime import date
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.db.models import Q
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Account, AccountCategory, AccountMovement
from account.services import AccountMovementService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from user.access_policy import BaseRule

from account.tests.test_services.common_account_movement import NOW, AccountMovementServiceCommonMixin


class MovementsOfAccountsWithCategoriesRule(BaseRule):
    """ A rule crossing a to-many relation: a movement joins once per category of
    its account. The project declares no rule on the movements.

    Registering it is harmless for the rest of the suite: a rule only applies to
    the roles naming it, and no fixture does.
    """

    identifier: str = "test_movement_account_with_categories"
    model = AccountMovement
    name = "Movements of accounts with categories"
    operations = ["read"]

    def scope_filter(self, context) -> Q:
        return Q(account__categories__isnull=False)


class GeneralCategoriesRule(BaseRule):
    """ Only the general categories, to group by a relation partly out of reach. """

    identifier: str = "test_category_general_only"
    model = AccountCategory
    name = "General categories only"
    operations = ["read"]

    def scope_filter(self, context) -> Q:
        return Q(account__isnull=True)


@freeze_time(NOW)
class AccountMovementGroupByServiceTest(AccountMovementServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `group_by` over the ledger, plus three movements in September, so that it
    spans two months and two accounts:

        2026-09-03  BREE   -12.30  Ale
        2026-09-20  SHIRE  +40.00  -
        2026-09-25  SHIRE  -80.00  Second Breakfast
        2026-10-15  SHIRE +150.00  -                 <Lobelia>  (ledger)
        2026-10-15  SHIRE  -80.00  Second Breakfast             (ledger)
        2026-10-15  SHIRE  -20.50  Pipe-weed         <Tobold>   (ledger)
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        AccountMovement.objects.bulk_create([
            AccountMovement(
                account=cls.account_bree, amount=Decimal("-12.30"), name="Ale",
                date=date(2026, 9, 3), category=cls.category_bree,
            ),
            AccountMovement(account=cls.account_shire, amount=Decimal("40.00"), name="Mathom sale", date=date(2026, 9, 20)),
            AccountMovement(
                account=cls.account_shire, amount=Decimal("-80.00"), name="Second breakfast",
                date=date(2026, 9, 25), category=cls.category_general,
            ),
        ])
        Account.objects.refresh_computed()

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountMovementService, user=self.user_frodon)

    # ------------------------------------------
    # Group By
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the number of groups, the groups, then one query per
            # relation grouped by, whatever the number of groups.
            ("an account", ["account"], 4, lambda self: [(self.account_shire,), (self.account_bree,)]),
            (
                "a contact, null last",
                ["contact"],
                4,
                lambda self: [(self.contact_lobelia,), (self.contact_tobold,), (None,)],
            ),
            ("a period", ["date_month"], 3, lambda self: [(date(2026, 9, 1),), (date(2026, 10, 1),)]),
            (
                "a period and a category",
                ["date_month", "category"],
                4,
                lambda self: [
                    (date(2026, 9, 1), self.category_general),
                    (date(2026, 9, 1), self.category_bree),
                    (date(2026, 9, 1), None),
                    (date(2026, 10, 1), self.category_general),
                    (date(2026, 10, 1), self.category_shire),
                    (date(2026, 10, 1), None),
                ],
            ),
        ]
    )
    def test_group_by_dimensions(self, label, dimensions, query_count, expected):
        with self.assertNumQueries(query_count):
            total, rows = async_to_sync(self.service.group_by)(dimensions, ["count"])

        keys = [tuple(row[name] for name in dimensions) for row in rows]
        self.assertEqual((total, keys), (len(expected(self)), expected(self)))

    @parameterized.expand(
        [
            ("date_day", [date(2026, 9, 3), date(2026, 9, 20), date(2026, 9, 25), date(2026, 10, 15)]),
            ("date_week", [date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 21), date(2026, 10, 12)]),
            ("date_month", [date(2026, 9, 1), date(2026, 10, 1)]),
            ("date_quarter", [date(2026, 7, 1), date(2026, 10, 1)]),
            ("date_year", [date(2026, 1, 1)]),
        ]
    )
    def test_group_by_dimensions_of_a_date(self, dimension, periods):
        with self.assertNumQueries(3):
            total, rows = async_to_sync(self.service.group_by)([dimension], ["count"])

        self.assertEqual((total, [row[dimension] for row in rows]), (len(periods), periods))

    @parameterized.expand(
        [
            # The sum is the balance; BREE has no credit: a null, not a zero.
            (
                "count and sums",
                ["count", "amount_sum", "debit_sum", "credit_sum"],
                [
                    ("SHIRE", 5, Decimal("9.50"), Decimal("-180.50"), Decimal("190.00")),
                    ("BREE", 1, Decimal("-12.30"), Decimal("-12.30"), None),
                ],
            ),
            (
                "min and max",
                ["amount_min", "amount_max"],
                [("SHIRE", Decimal("-80.00"), Decimal("150.00")), ("BREE", Decimal("-12.30"), Decimal("-12.30"))],
            ),
        ]
    )
    def test_group_by_measures(self, label, measures, expected):
        with self.assertNumQueries(4):
            total, rows = async_to_sync(self.service.group_by)(["account"], measures)

        self.assertEqual(total, 2)
        self.assertEqual([(row["account"].code, *[row[name] for name in measures]) for row in rows], expected)

    @parameterized.expand(
        [
            # The share of each category in the expenses of its month.
            (
                "the expenses",
                {"amount__lt": 0},
                4,
                [(9, "Second Breakfast", 86.67), (9, "Ale", 13.33), (10, "Second Breakfast", 79.6), (10, "Pipe-weed", 20.4)],
            ),
            ("one account", {"account__code": "BREE"}, 4, [(9, "Ale", 100.0)]),
            # No group: no category to load.
            ("nothing matches", {"amount__gt": 1000}, 3, []),
        ]
    )
    def test_group_by_filters(self, label, filters, query_count, expected):
        with self.assertNumQueries(query_count):
            total, rows = async_to_sync(self.service.group_by)(["date_month", "category"], ["amount_share"], filters=filters)

        self.assertEqual(
            [(row["date_month"].month, row["category"].name, round(row["amount_share"], 2)) for row in rows],
            expected,
        )
        self.assertEqual(total, len(expected))

    @parameterized.expand(
        [
            # -160 (2), -20.50 (1), -12.30 (1), uncategorized +190 (2). By pk,
            # Second Breakfast < Pipe-weed < Ale, and null last whatever the direction.
            ("by a measure", ["-amount_sum"], [None, "Ale", "Pipe-weed", "Second Breakfast"]),
            ("by a measure, then a key", ["count", "-category"], ["Ale", "Pipe-weed", "Second Breakfast", None]),
            ("by default, the keys", None, ["Second Breakfast", "Pipe-weed", "Ale", None]),
        ]
    )
    def test_group_by_ordering(self, label, ordering, names):
        with self.assertNumQueries(4):
            total, rows = async_to_sync(self.service.group_by)(["category"], ["amount_sum", "count"], ordering=ordering)

        self.assertEqual([row["category"].name if row["category"] else None for row in rows], names)

    @parameterized.expand(
        [
            ("a first page", 2, 0, [date(2026, 10, 15), date(2026, 9, 25)]),
            ("a page further", 2, 1, [date(2026, 9, 25), date(2026, 9, 20)]),
            ("past the end", 2, 4, []),
        ]
    )
    def test_group_by_pagination(self, label, limit, offset, expected):
        with self.assertNumQueries(3):
            total, rows = async_to_sync(self.service.group_by)(
                ["date_day"], ["count"], ordering=["-date_day"], limit=limit, offset=offset
            )

        # The total counts every group, not only those of the page.
        self.assertEqual((total, [row["date_day"] for row in rows]), (4, expected))

    @parameterized.expand(
        [
            ("unknown dimension", {"dimensions": ["date"]}, "dimensions"),
            ("unknown measure", {"measures": ["amount"]}, "measures"),
            ("ordering not asked", {"ordering": ["-amount_sum"]}, "ordering"),
            ("offset without limit", {"offset": 1}, "offset"),
        ]
    )
    def test_group_by_invalid(self, label, arguments, key):
        arguments = {"dimensions": ["account"], "measures": ["count"], **arguments}

        with self.assertNumQueries(0):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.group_by)(**arguments)

        self.assertEqual(list(ctx.exception.dict()["__all__"]), [key])

    @parameterized.expand(
        [
            ("no rule", [], ["SHIRE", "BREE"], [5, 1], [Decimal("9.50"), Decimal("-12.30")]),
            # SHIRE has two categories once Mushrooms is added, so each of its
            # movements joins twice: the sums must not see it.
            ("a rule crossing a to-many relation", ["test_movement_account_with_categories"], ["SHIRE", "BREE"], [5, 1], [Decimal("9.50"), Decimal("-12.30")]),
            ("anonymous: no role, no rule", None, ["SHIRE", "BREE"], [5, 1], [Decimal("9.50"), Decimal("-12.30")]),
        ]
    )
    def test_group_by_access_rules(self, label, rules, codes, counts, sums):
        AccountCategory.objects.create(name="Mushrooms", account=self.account_shire)
        service = self.service_with_rules(rules)

        # An anonymous caller has no role to read.
        with self.assertNumQueries(3 if rules is None else 4):
            total, rows = async_to_sync(service.group_by)(["account"], ["count", "amount_sum"])

        self.assertEqual(
            [(row["account"].code, row["count"], row["amount_sum"]) for row in rows],
            list(zip(codes, counts, sums)),
        )

    @parameterized.expand(
        [
            ("no rule", [], ["Second Breakfast", "Pipe-weed", "Ale", None]),
            # A category the acting user may not read stays its bare pk.
            ("general categories only", ["test_category_general_only"], ["Second Breakfast", "pk", "pk", None]),
        ]
    )
    def test_group_by_access_rules_of_a_relation(self, label, rules, names):
        service = self.service_with_rules(rules)

        with self.assertNumQueries(4):
            total, rows = async_to_sync(service.group_by)(["category"], ["count"])

        self.assertEqual(
            [
                None if row["category"] is None
                else "pk" if isinstance(row["category"], str)
                else row["category"].name
                for row in rows
            ],
            names,
        )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def service_with_rules(self, rules):
        """ The service acting as Frodon, whose role holds `rules`. `rules=None` is
        an anonymous caller. """
        if rules is None:
            return self.get_service(AccountMovementService)
        self.role.rules = rules
        self.role.save()
        return self.get_service(AccountMovementService, user=self.user_frodon)
