from datetime import timedelta

from asgiref.sync import async_to_sync
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import AccountMovement
from account.schemas import AccountMovementCreateSchema, AccountMovementUpdateSchema
from account.services import AccountMovementService
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
    AccountTestMixin,
)

NOW = "2026-10-15 10:00:00"
PAST = "2026-10-01T09:30:00Z"
FUTURE = "2026-10-16T09:30:00Z"


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
        # Resolution of the account and the category, the insert, then the refresh
        # of the stored totals of that one account.
        with self.assertNumQueries(11):
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

    def test_create_now_is_not_the_future(self):
        data = AccountMovementCreateSchema(**self._payload(date=timezone.now().isoformat()))
        async_to_sync(self.service.create)([data])

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
            ("amount", {"amount": "200"}, 10),
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
            account_id=ACCOUNT_ID2, amount="-3", name="Fee", date=timezone.now() - timedelta(days=1)
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
