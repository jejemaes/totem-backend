from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import AccountCategory, AccountMovement
from account.schemas import AccountMovementCreateSchema, AccountMovementUpdateSchema
from account.services import AccountCategoryService, AccountMovementService
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError

from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    MOVEMENT_ID1,
    MOVEMENT_ID2,
    MOVEMENT_ID3,
    AccountGroupByTestMixin,
    AccountTestMixin,
)

NOW = "2026-10-15 10:00:00"
PAST = "2026-10-01"
FUTURE = "2026-10-16"


@freeze_time(NOW)
class TestAccountMovementService(AccountTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(AccountMovementService)

    def _payload(self, **values):
        return {"account": ACCOUNT_ID2, "amount": "-12.30", "name": "Fee", "date": PAST, **values}

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("missing account", {"amount": "1", "name": "x", "date": PAST}),
            ("missing amount", {"account": ACCOUNT_ID1, "name": "x", "date": PAST}),
            ("missing name", {"account": ACCOUNT_ID1, "amount": "1", "date": PAST}),
            ("missing date", {"account": ACCOUNT_ID1, "amount": "1", "name": "x"}),
            ("too many decimals", {"account": ACCOUNT_ID1, "amount": "1.001", "name": "x", "date": PAST}),
            ("not a date", {"account": ACCOUNT_ID1, "amount": "1", "name": "x", "date": "yesterday"}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                AccountMovementCreateSchema(**payload)

    def test_update_schema_has_no_account(self):
        # A movement does not change account: see the schema module.
        self.assertNotIn("account", AccountMovementUpdateSchema.model_fields)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("debit", {}, "-12.30", "0", "-12.30"),
            ("credit", {"amount": "1000"}, "0", "1000.00", "1000.00"),
            ("general category", {"category": CATEGORY_GENERAL_ID}, "-12.30", "0", "-12.30"),
            ("own category", {"category": CATEGORY_BANK_ID}, "-12.30", "0", "-12.30"),
            ("full", {"description": "Monthly", "reference": "B-42"}, "-12.30", "0", "-12.30"),
        ]
    )
    def test_create_valid(self, dummy, values, debit, credit, balance):
        data = AccountMovementCreateSchema(**self._payload(**values))
        async_to_sync(self.service.create)([data])

        self.assertTotals(ACCOUNT_ID2, debit, credit, balance)

    def test_create_query_count(self):
        data = AccountMovementCreateSchema(**self._payload(category=CATEGORY_GENERAL_ID))
        # Resolution of the account and the category, the insert, the lookup of the
        # budget positions of the category, then the refresh of the stored totals of
        # that one account.
        with self.assertNumQueries(12):
            async_to_sync(self.service.create)([data])

    def test_create_many_refreshes_each_account_once(self):
        data = [
            AccountMovementCreateSchema(**self._payload(amount="-1")),
            AccountMovementCreateSchema(**self._payload(amount="5")),
            AccountMovementCreateSchema(**self._payload(account=ACCOUNT_ID1, amount="10")),
        ]
        async_to_sync(self.service.create)(data)

        self.assertTotals(ACCOUNT_ID1, "-100.50", "160.00", "59.50")
        self.assertTotals(ACCOUNT_ID2, "-1.00", "5.00", "4.00")

    @parameterized.expand(
        [
            ("zero amount", {"amount": "0"}, "amount"),
            ("future date", {"date": FUTURE}, "date"),
            ("other account's category", {"category": CATEGORY_SHOP_ID}, "category"),
            ("unknown account", {"account": "01JA0000000000000000000099"}, "account"),
            ("unknown category", {"category": "01JC0000000000000000000099"}, "category"),
        ]
    )
    def test_create_invalid(self, dummy, values, error_key):
        data = AccountMovementCreateSchema(**self._payload(**values))
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([data])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertFalse(AccountMovement.objects.filter(account_id=ACCOUNT_ID2).exists())

    def test_create_reports_every_error(self):
        data = AccountMovementCreateSchema(
            **self._payload(amount="0", date=FUTURE, category=CATEGORY_SHOP_ID)
        )
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([data])

        self.assertEqual(set(ctx.exception.dict()[0]), {"amount", "date", "category"})

    def test_create_today_is_not_the_future(self):
        data = AccountMovementCreateSchema(**self._payload(date=timezone.localdate().isoformat()))
        async_to_sync(self.service.create)([data])

    def test_date_refuses_a_time(self):
        # A date, not a datetime: a time of day is no part of a movement.
        with self.assertRaises(PydanticValidationError):
            AccountMovementCreateSchema(**self._payload(date="2026-10-01T09:30:00Z"))

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"account": ACCOUNT_ID1}, ["id", "amount"], 2, 3),
            ({"account": ACCOUNT_ID2}, ["id", "amount"], 2, 0),
            ({"amount__lt": 0}, ["id", "account", "category"], 2, 2),
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields)
            self.assertEqual(len(qs), expected_count)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("amount", {"id": MOVEMENT_ID1}, {"amount": "200"}, ("-100.50", "200.00", "99.50")),
            ("debit to credit", {"id": MOVEMENT_ID2}, {"amount": "80"}, ("-20.50", "230.00", "209.50")),
            ("label only", {"id": MOVEMENT_ID1}, {"name": "Big sale"}, ("-100.50", "150.00", "49.50")),
            ("general category", {"id": MOVEMENT_ID1}, {"category": CATEGORY_GENERAL_ID}, ("-100.50", "150.00", "49.50")),
            ("own category", {"id": MOVEMENT_ID1}, {"category": CATEGORY_SHOP_ID}, ("-100.50", "150.00", "49.50")),
            ("no category", {"id": MOVEMENT_ID3}, {"category": None}, ("-100.50", "150.00", "49.50")),
            ("every debit", {"amount__lt": 0}, {"amount": "-1"}, ("-2.00", "150.00", "148.00")),
        ]
    )
    def test_update_valid(self, dummy, filters, payload, totals):
        data = AccountMovementUpdateSchema(**payload)
        count, queryset = async_to_sync(self.service.update)(filters, data)

        self.assertEqual(count, AccountMovement.objects.filter(**filters).count())
        self.assertTotals(ACCOUNT_ID1, *totals)

    @parameterized.expand(
        [
            # Only what the totals read refreshes them: a label costs no recompute.
            ("label only", {"name": "Big sale"}, 5),
            ("amount", {"amount": "200"}, 11),
        ]
    )
    def test_update_query_count(self, dummy, payload, query_count):
        data = AccountMovementUpdateSchema(**payload)
        with self.assertNumQueries(query_count):
            async_to_sync(self.service.update)({"id": MOVEMENT_ID1}, data)

    def test_update_not_found(self):
        count, queryset = async_to_sync(self.service.update)(
            {"id": "01JM0000000000000000000099"}, AccountMovementUpdateSchema(name="Nothing")
        )
        self.assertEqual(count, 0)

    @parameterized.expand(
        [
            ("zero amount", {"amount": "0"}, "amount"),
            ("future date", {"date": FUTURE}, "date"),
            ("other account's category", {"category": CATEGORY_BANK_ID}, "category"),
        ]
    )
    def test_update_invalid(self, dummy, payload, error_key):
        data = AccountMovementUpdateSchema(**payload)
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)({"id": MOVEMENT_ID1}, data)

        # Keyed by the pk of the record, not by the payload index.
        self.assertEqual(list(ctx.exception.dict()[MOVEMENT_ID1]), [error_key])
        self.assertTotals(ACCOUNT_ID1, "-100.50", "150.00", "49.50")

    def test_update_checks_the_category_against_each_movement(self):
        # One payload, movements of two accounts: SHOP's category fits one of them.
        bank_movement = AccountMovement.objects.create(
            account_id=ACCOUNT_ID2, amount="-3", name="Fee", date=timezone.localdate() - timedelta(days=1)
        )
        data = AccountMovementUpdateSchema(category=CATEGORY_SHOP_ID)
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)({"id__in": [MOVEMENT_ID1, bank_movement.pk]}, data)

        self.assertEqual(list(ctx.exception.dict()), [bank_movement.pk])

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"id": MOVEMENT_ID1}, 1, ("-100.50", "0", "-100.50")),
            ({"amount__lt": 0}, 2, ("0", "150.00", "150.00")),
            ({"account": ACCOUNT_ID1}, 3, ("0", "0", "0")),
            ({"id": "01JM0000000000000000000099"}, 0, ("-100.50", "150.00", "49.50")),
        ]
    )
    def test_delete_valid(self, filters, affected_row, totals):
        count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected_row)
        self.assertTotals(ACCOUNT_ID1, *totals)


@freeze_time(NOW)
class TestAccountMovementGroupBy(AccountGroupByTestMixin, TestCase):
    """`group_by` over the ledger of `AccountGroupByTestMixin`."""

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(AccountMovementService)

    def group_by(self, *args, **kwargs):
        return async_to_sync(self.service.group_by)(*args, **kwargs)

    def test_group_by_measures(self):
        total, rows = self.group_by(["account"], ["count", "amount_sum", "debit_sum", "credit_sum"])

        self.assertEqual(total, 2)
        # The sum is the balance; BANK has no credit, a NULL rather than a zero.
        self.assertEqual(
            [(row["account"], row["count"], row["amount_sum"], row["debit_sum"], row["credit_sum"]) for row in rows],
            [
                (self.account_shop, 5, Decimal("9.50"), Decimal("-180.50"), Decimal("190.00")),
                (self.account_bank, 1, Decimal("-12.30"), Decimal("-12.30"), None),
            ],
        )

    @parameterized.expand(
        [
            ("date_day", [date(2026, 9, 3), date(2026, 9, 20), date(2026, 9, 25), date(2026, 10, 15)]),
            ("date_week", [date(2026, 8, 31), date(2026, 9, 14), date(2026, 9, 21), date(2026, 10, 12)]),
            ("date_month", [date(2026, 9, 1), date(2026, 10, 1)]),
            ("date_quarter", [date(2026, 7, 1), date(2026, 10, 1)]),
            ("date_year", [date(2026, 1, 1)]),
        ]
    )
    def test_group_by_date(self, dimension, periods):
        total, rows = self.group_by([dimension], ["count"])

        self.assertEqual((total, [row[dimension] for row in rows]), (len(periods), periods))

    def test_group_by_null_group(self):
        total, rows = self.group_by(["date_month", "category"], ["amount_sum"])

        self.assertEqual(
            [(row["date_month"], row["category"], row["amount_sum"]) for row in rows],
            [
                (date(2026, 9, 1), self.category_general, Decimal("-80.00")),
                (date(2026, 9, 1), self.category_bank, Decimal("-12.30")),
                (date(2026, 9, 1), None, Decimal("40.00")),
                (date(2026, 10, 1), self.category_general, Decimal("-80.00")),
                (date(2026, 10, 1), self.category_shop, Decimal("-20.50")),
                (date(2026, 10, 1), None, Decimal("150.00")),
            ],
        )

    def test_group_by_share(self):
        # The share of each category in the expenses of its month.
        total, rows = self.group_by(["date_month", "category"], ["amount_share"], filters={"amount__lt": 0})

        self.assertEqual(
            [(row["date_month"].month, row["category"], round(row["amount_share"], 2)) for row in rows],
            [
                (9, self.category_general, 86.67),
                (9, self.category_bank, 13.33),
                (10, self.category_general, 79.6),
                (10, self.category_shop, 20.4),
            ],
        )

    @parameterized.expand(
        [
            ("by a measure", ["-amount_sum"], [None, "Fees", "Stock", "Rent"]),
            ("by a measure, then a key", ["count", "-category"], ["Fees", "Stock", "Rent", None]),
            ("by default, the keys", None, ["Rent", "Stock", "Fees", None]),
        ]
    )
    def test_group_by_ordering(self, dummy, ordering, names):
        # Rent -160 (2), Stock -20.50 (1), Fees -12.30 (1), none +190 (2). By pk,
        # Rent < Stock < Fees, and NULL last whatever the direction.
        total, rows = self.group_by(["category"], ["amount_sum", "count"], ordering=ordering)

        self.assertEqual([row["category"].name if row["category"] else None for row in rows], names)

    def test_group_by_pagination(self):
        total, rows = self.group_by(["date_day"], ["count"], ordering=["-date_day"], limit=2, offset=1)

        self.assertEqual((total, [row["date_day"] for row in rows]), (4, [date(2026, 9, 25), date(2026, 9, 20)]))

    def test_group_by_access_rules(self):
        # A rule crossing a to-many relation: SHOP has two categories, so each of
        # its movements joins twice. The sums must not see it.
        AccountCategory.objects.create(name="Packaging", account=self.account_shop)

        async def apply_access_rules(service, queryset, operation):
            return queryset.filter(account__categories__isnull=False)

        with mock.patch.object(AccountMovementService, "apply_access_rules", apply_access_rules):
            total, rows = self.group_by(["account"], ["count", "amount_sum"])

        self.assertEqual(
            [(row["account"], row["count"], row["amount_sum"]) for row in rows],
            [(self.account_shop, 5, Decimal("9.50")), (self.account_bank, 1, Decimal("-12.30"))],
        )

    def test_group_by_access_rules_of_a_category(self):
        # A category the user may not read stays its bare pk.
        async def apply_access_rules(service, queryset, operation):
            return queryset.filter(account__isnull=True)

        with mock.patch.object(AccountCategoryService, "apply_access_rules", apply_access_rules):
            total, rows = self.group_by(["category"], ["count"])

        self.assertEqual(
            [row["category"] for row in rows],
            [self.category_general, self.category_shop.pk, self.category_bank.pk, None],
        )

    @parameterized.expand(
        [
            ("unknown dimension", {"dimensions": ["date"]}, "dimensions"),
            ("unknown measure", {"measures": ["amount"]}, "measures"),
            ("ordering not asked", {"ordering": ["-amount_sum"]}, "ordering"),
            ("offset without limit", {"offset": 1}, "offset"),
        ]
    )
    def test_group_by_invalid(self, dummy, arguments, key):
        arguments = {"dimensions": ["account"], "measures": ["count"], **arguments}

        with self.assertNumQueries(0):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                self.group_by(**arguments)

        self.assertEqual(list(ctx.exception.dict()["__all__"]), [key])

    def test_group_by_query_count(self):
        # The roles of the user, the number of groups, the groups, then one query
        # per relation grouped by -- whatever the number of groups.
        with self.assertNumQueries(5):
            self.group_by(["account", "category"], ["count"])
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(AccountMovementService)
        with self.assertNumQueries(3):
            self.group_by(["date_month"], ["count", "amount_share"])
