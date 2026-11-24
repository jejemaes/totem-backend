from datetime import date
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountMovement
from account.schemas import AccountMovementCreateSchema, AccountMovementUpdateSchema
from account.services import AccountMovementService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account import ACCOUNT_BREE_ID, ACCOUNT_SHIRE_ID, ACCOUNT_UNKNOWN_ID
from account.tests.test_services.common_account_category import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    CATEGORY_UNKNOWN_ID,
)
from account.tests.test_services.common_account_movement import (
    CONTACT_LOBELIA_ID,
    CONTACT_TOBOLD_ID,
    MOVEMENT_BREAKFAST_ID,
    MOVEMENT_PIPEWEED_ID,
    MOVEMENT_SALE_ID,
    MOVEMENT_UNKNOWN_ID,
    NOW,
    AccountMovementServiceCommonMixin,
)

ALL_MOVEMENT_IDS = [MOVEMENT_SALE_ID, MOVEMENT_BREAKFAST_ID, MOVEMENT_PIPEWEED_ID]

PAST = "2026-10-01"
FUTURE = "2026-10-16"

# The totals of SHIRE, as the ledger leaves them.
SHIRE_TOTALS = ("-100.50", "150.00", "49.50")


@freeze_time(NOW)
class AccountMovementServiceTest(AccountMovementServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `AccountMovementService`: create, read, update, delete. Every write goes
    stale the stored totals of the accounts it touches, refreshed before it
    commits: each test reads them back.

    No access rules tests: no `BaseRule` is registered for `AccountMovement`.
    """

    payload_create = {"account": ACCOUNT_BREE_ID, "amount": "-12.30", "name": "Bar tab", "date": PAST}

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountMovementService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the account, the insert, then the refresh of the totals of
            # that one account.
            ("a debit", {}, 11, {"amount": Decimal("-12.30")}, ("-12.30", "0", "-12.30")),
            ("a credit", {"amount": "1000"}, 11, {"amount": Decimal("1000.00")}, ("0", "1000.00", "1000.00")),
            # The category costs its resolution, and the lookup of its positions.
            ("a general category", {"category": CATEGORY_GENERAL_ID}, 12, {"category_id": CATEGORY_GENERAL_ID}, ("-12.30", "0", "-12.30")),
            ("the account's category", {"category": CATEGORY_BREE_ID}, 12, {"category_id": CATEGORY_BREE_ID}, ("-12.30", "0", "-12.30")),
            (
                "every field",
                {"description": "Monthly", "reference": "B-42", "contact": CONTACT_TOBOLD_ID},
                12,
                {"description": "Monthly", "reference": "B-42", "contact_id": CONTACT_TOBOLD_ID},
                ("-12.30", "0", "-12.30"),
            ),
            # Today in the timezone of the site is not the future.
            ("today", {"date": "2026-10-15"}, 11, {"date": date(2026, 10, 15)}, ("-12.30", "0", "-12.30")),
        ]
    )
    def test_create(self, label, values, query_count, expected_values, totals):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([AccountMovementCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual([movement.name for movement in instances], ["Bar tab"])
        movement = AccountMovement.objects.get(pk=instances[0].pk)
        self.assertEqual(movement.account_id, ACCOUNT_BREE_ID)
        self.assertEqual({name: getattr(movement, name) for name in expected_values}, expected_values)
        self.assertAccountTotals(ACCOUNT_BREE_ID, *totals)
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, *SHIRE_TOTALS)

    @parameterized.expand(
        [
            # `validate_data`, keyed by the index of the payload, inside the
            # transaction: the relations are resolved, and the insert not issued.
            ("zero amount", {"amount": "0"}, 5, ["amount"]),
            ("future date", {"date": FUTURE}, 5, ["date"]),
            ("another account's category", {"category": CATEGORY_SHIRE_ID}, 6, ["category"]),
            ("every error at once", {"amount": "0", "date": FUTURE, "category": CATEGORY_SHIRE_ID}, 6, ["amount", "date", "category"]),
        ]
    )
    def test_create_invalid(self, label, values, query_count, error_keys):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([AccountMovementCreateSchema(**{**self.payload_create, **values})])

        self.assertCountEqual(ctx.exception.dict()[0], error_keys)
        self.assertFalse(AccountMovement.objects.filter(account_id=ACCOUNT_BREE_ID).exists())
        self.assertAccountTotals(ACCOUNT_BREE_ID, "0", "0", "0")

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([self.payload_create])

        self.assertEqual(AccountMovement.objects.count(), 3)

    @parameterized.expand(
        [
            # The roles, then one query per relation given, before the transaction.
            ("unknown account", {"account": ACCOUNT_UNKNOWN_ID}, 2, "account"),
            ("unknown category", {"category": CATEGORY_UNKNOWN_ID}, 3, "category"),
            ("unknown contact", {"contact": "01JK0000000000000000000099"}, 3, "contact"),
        ]
    )
    def test_create_relations(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([AccountMovementCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(AccountMovement.objects.count(), 3)

    @parameterized.expand(
        [
            # Each account touched is refreshed once, whatever its number of movements.
            (
                "every input valid",
                [{"amount": "-1"}, {"amount": "5"}, {"account": ACCOUNT_SHIRE_ID, "amount": "10"}],
                11,
                None,
                [("-1.00", "5.00", "4.00"), ("-100.50", "160.00", "59.50")],
            ),
            # All or nothing: the valid inputs are not written either.
            (
                "the second input invalid",
                [{"amount": "-1"}, {"amount": "0"}, {"account": ACCOUNT_SHIRE_ID, "amount": "10"}],
                5,
                {1: ["amount"]},
                [("0", "0", "0"), SHIRE_TOTALS],
            ),
        ]
    )
    def test_create_batch(self, label, values_list, query_count, errors, totals):
        data = [AccountMovementCreateSchema(**{**self.payload_create, **values}) for values in values_list]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual(len(instances), 3)
            self.assertEqual(AccountMovement.objects.count(), 6)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertEqual(AccountMovement.objects.count(), 3)
        self.assertAccountTotals(ACCOUNT_BREE_ID, *totals[0])
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, *totals[1])

    @parameterized.expand(
        [
            # No default: the model has none on a field of the body.
            ("every field", None, {}),
            ("the fields asked", ["date", "amount"], {}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, expected)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ALL_MOVEMENT_IDS),
            ("of an account", {"account": ACCOUNT_SHIRE_ID}, ALL_MOVEMENT_IDS),
            ("of an account without movement", {"account": ACCOUNT_BREE_ID}, []),
            ("the debits", {"amount__lt": 0}, [MOVEMENT_BREAKFAST_ID, MOVEMENT_PIPEWEED_ID]),
            ("uncategorized", {"category__isnull": True}, [MOVEMENT_SALE_ID]),
            ("of a contact", {"contact": CONTACT_LOBELIA_ID}, [MOVEMENT_SALE_ID]),
            ("by reference", {"reference": "INV-001"}, [MOVEMENT_SALE_ID]),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [movement.pk for movement in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by amount", ["amount"], [MOVEMENT_BREAKFAST_ID, MOVEMENT_PIPEWEED_ID, MOVEMENT_SALE_ID]),
            ("by name, descending", ["-name"], [MOVEMENT_BREAKFAST_ID, MOVEMENT_PIPEWEED_ID, MOVEMENT_SALE_ID]),
            ("by date, then amount", ["-date", "-amount"], [MOVEMENT_SALE_ID, MOVEMENT_PIPEWEED_ID, MOVEMENT_BREAKFAST_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [movement.pk for movement in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "amount"], 2, []),
            # Each relation asked is prefetched with the fields asked on it.
            ("the category", ["id", "category__name"], 3, ["category"]),
            ("every relation", ["id", "account__code", "category__name", "contact__first_name"], 5, ["account", "category", "contact"]),
        ]
    )
    def test_read_fields(self, label, fields, query_count, relations):
        with self.assertNumQueries(query_count):
            movements = list(async_to_sync(self.service.read)({"id": MOVEMENT_PIPEWEED_ID}, fields=fields))
            loaded = {name: getattr(movements[0], name) for name in relations}

        self.assertIn("description", movements[0].get_deferred_fields())
        self.assertEqual(
            {name: value.pk for name, value in loaded.items()},
            {
                name: pk for name, pk in
                [("account", ACCOUNT_SHIRE_ID), ("category", CATEGORY_SHIRE_ID), ("contact", CONTACT_TOBOLD_ID)]
                if name in relations
            },
        )

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            # Only what the totals read refreshes them: a label costs no refresh. A
            # category costs its resolution, and the positions reading it.
            ("the label", MOVEMENT_SALE_ID, {"name": "Mathom auction"}, 5, {"name": "Mathom auction"}, SHIRE_TOTALS),
            ("the amount", MOVEMENT_SALE_ID, {"amount": "200"}, 11, {"amount": Decimal("200.00")}, ("-100.50", "200.00", "99.50")),
            ("a debit to a credit", MOVEMENT_BREAKFAST_ID, {"amount": "80"}, 11, {"amount": Decimal("80.00")}, ("-20.50", "230.00", "209.50")),
            ("a general category", MOVEMENT_SALE_ID, {"category": CATEGORY_GENERAL_ID}, 8, {"category_id": CATEGORY_GENERAL_ID}, SHIRE_TOTALS),
            ("the account's category", MOVEMENT_SALE_ID, {"category": CATEGORY_SHIRE_ID}, 8, {"category_id": CATEGORY_SHIRE_ID}, SHIRE_TOTALS),
            ("the category emptied", MOVEMENT_PIPEWEED_ID, {"category": None}, 7, {"category_id": None}, SHIRE_TOTALS),
            ("the contact emptied", MOVEMENT_SALE_ID, {"contact": None}, 5, {"contact_id": None}, SHIRE_TOTALS),
        ]
    )
    def test_update(self, label, pk, payload, query_count, expected_values, totals):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": pk}, AccountMovementUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([movement.pk for movement in queryset], [pk])
        movement = AccountMovement.objects.get(pk=pk)
        self.assertEqual({name: getattr(movement, name) for name in expected_values}, expected_values)
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, *totals)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": MOVEMENT_SALE_ID}, AccountMovementUpdateSchema(description="Old mathoms"))

        movement = AccountMovement.objects.get(pk=MOVEMENT_SALE_ID)
        self.assertEqual(
            (movement.name, movement.amount, movement.reference, movement.contact_id, movement.description),
            ("Mathom sale", Decimal("150.00"), "INV-001", CONTACT_LOBELIA_ID, "Old mathoms"),
        )

    @parameterized.expand(
        [
            # `validate_data` during an update: keyed by the pk of the record.
            ("zero amount", {"amount": "0"}, 5, {MOVEMENT_SALE_ID: ["amount"]}),
            ("future date", {"date": FUTURE}, 5, {MOVEMENT_SALE_ID: ["date"]}),
            ("another account's category", {"category": CATEGORY_BREE_ID}, 6, {MOVEMENT_SALE_ID: ["category"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown category", {"category": CATEGORY_UNKNOWN_ID}, 2, {0: ["category"]}),
        ]
    )
    def test_update_invalid(self, label, payload, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": MOVEMENT_SALE_ID}, AccountMovementUpdateSchema(**payload))

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        movement = AccountMovement.objects.get(pk=MOVEMENT_SALE_ID)
        self.assertEqual((movement.amount, movement.category_id), (Decimal("150.00"), None))
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, *SHIRE_TOTALS)

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": MOVEMENT_SALE_ID}, {"amount": "1"})

        self.assertEqual(AccountMovement.objects.get(pk=MOVEMENT_SALE_ID).amount, Decimal("150.00"))

    def test_update_batch(self):
        with self.assertNumQueries(11):
            count, queryset = async_to_sync(self.service.update)({"amount__lt": 0}, AccountMovementUpdateSchema(amount="-1"))

        self.assertEqual(count, 2)
        self.assertCountEqual([movement.pk for movement in queryset], [MOVEMENT_BREAKFAST_ID, MOVEMENT_PIPEWEED_ID])
        self.assertEqual(AccountMovement.objects.filter(amount=Decimal("-1")).count(), 2)
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, "-2.00", "150.00", "148.00")

    def test_update_batch_checks_each_record(self):
        # One payload, movements of two accounts: SHIRE's category fits one of
        # them only. Nothing is written, and only the other one is reported.
        bree_movement = AccountMovement.objects.create(account_id=ACCOUNT_BREE_ID, amount="-3", name="Ale", date=PAST)

        with self.assertNumQueries(6):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)(
                    {"id__in": [MOVEMENT_SALE_ID, bree_movement.pk]}, AccountMovementUpdateSchema(category=CATEGORY_SHIRE_ID)
                )

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, {bree_movement.pk: ["category"]})
        self.assertEqual(
            list(AccountMovement.objects.filter(category_id=CATEGORY_SHIRE_ID).values_list("pk", flat=True)),
            [MOVEMENT_PIPEWEED_ID],
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": MOVEMENT_UNKNOWN_ID}, AccountMovementUpdateSchema(name="Lembas"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(AccountMovement.objects.filter(name="Lembas").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # The rows, the delete, then the refresh of the account's totals.
            ("one movement", {"id": MOVEMENT_SALE_ID}, 11, 1, ("-100.50", "0", "-100.50")),
            ("the debits", {"amount__lt": 0}, 11, 2, ("0", "150.00", "150.00")),
            ("a whole account", {"account": ACCOUNT_SHIRE_ID}, 11, 3, ("0", "0", "0")),
            ("nothing matches", {"id": MOVEMENT_UNKNOWN_ID}, 5, 0, SHIRE_TOTALS),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, totals):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertFalse(AccountMovement.objects.filter(**filters).exists())
        self.assertEqual(AccountMovement.objects.count(), 3 - affected)
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, *totals)
