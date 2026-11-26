from datetime import date
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountMovement
from account.schemas import AccountMovementUpdateSchema
from account.services import AccountMovementService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account_category import CATEGORY_SHIRE_ID
from account.tests.test_services.common_account_movement import (
    CONTACT_LOBELIA_ID,
    LEDGER_DATE,
    MOVEMENT_BREAKFAST_ID,
    NOW,
)
from account.tests.test_services.common_invoice import InvoiceServiceCommonMixin

MOVEMENT_BOOKED_ID = "01JM0000000000000000000010"


@freeze_time(NOW)
class AccountMovementOriginServiceTest(InvoiceServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ A movement booked from a document (`origin_type` set): the document owns
    its amount, date and reference, refused on update, and the movement itself,
    refused on delete; the rest is edited as on any movement.

    No access rules tests: no `BaseRule` is registered for `AccountMovement`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # As a payment of the Pipe-weed invoice books it.
        cls.movement_booked = AccountMovement.objects.create(
            id=MOVEMENT_BOOKED_ID, account=cls.account_shire, amount=Decimal("-30.00"),
            name="Payment TRF-1 - INV/2026/00001", date=LEDGER_DATE, reference="INV/2026/00001",
            contact=cls.contact_tobold, origin_type="invoice", invoice=cls.invoice_pipeweed,
        )

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountMovementService, user=self.user_frodon)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the name", {"name": "Old Toby"}, {"name": "Old Toby"}),
            ("the description", {"description": "Autumn stock"}, {"description": "Autumn stock"}),
            ("the category", {"category": CATEGORY_SHIRE_ID}, {"category_id": CATEGORY_SHIRE_ID}),
            ("the contact", {"contact": CONTACT_LOBELIA_ID}, {"contact_id": CONTACT_LOBELIA_ID}),
            ("no contact", {"contact": None}, {"contact_id": None}),
        ]
    )
    def test_update_editable(self, label, payload, expected):
        count, _queryset = async_to_sync(self.service.update)(
            {"id": MOVEMENT_BOOKED_ID}, AccountMovementUpdateSchema(**payload)
        )

        self.assertEqual(count, 1)
        movement = AccountMovement.objects.get(pk=MOVEMENT_BOOKED_ID)
        for name, value in expected.items():
            self.assertEqual(getattr(movement, name), value)
        # What the document owns is untouched.
        self.assertEqual(
            (movement.amount, movement.date, movement.reference, movement.origin_type, movement.invoice_id),
            (Decimal("-30.00"), LEDGER_DATE, "INV/2026/00001", "invoice", self.invoice_pipeweed.pk),
        )

    @parameterized.expand(
        [
            ("the amount", {"amount": "-12.00"}, ["amount"]),
            ("the date", {"date": "2026-10-01"}, ["date"]),
            ("the reference", {"reference": "OTHER"}, ["reference"]),
            ("a null reference", {"reference": None}, ["reference"]),
            # All or nothing: the name is not written either.
            ("with an editable field", {"name": "Old Toby", "amount": "-12.00"}, ["amount"]),
            ("all three", {"amount": "-12.00", "date": "2026-10-01", "reference": "OTHER"}, ["amount", "date", "reference"]),
        ]
    )
    def test_update_owned_by_the_document(self, label, payload, fields):
        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.update)({"id": MOVEMENT_BOOKED_ID}, AccountMovementUpdateSchema(**payload))

        # Keyed by the pk of the movement, as `validate_data` errors of an update.
        self.assertEqual(sorted(context.exception.dict()[MOVEMENT_BOOKED_ID]), fields)
        movement = AccountMovement.objects.get(pk=MOVEMENT_BOOKED_ID)
        self.assertEqual(
            (movement.name, movement.amount, movement.date, movement.reference),
            ("Payment TRF-1 - INV/2026/00001", Decimal("-30.00"), LEDGER_DATE, "INV/2026/00001"),
        )

    def test_update_a_manual_movement(self):
        # Without an origin, the amount, date and reference are its own.
        async_to_sync(self.service.update)(
            {"id": MOVEMENT_BREAKFAST_ID},
            AccountMovementUpdateSchema(amount="-90.00", date="2026-10-01", reference="B-1"),
        )

        movement = AccountMovement.objects.get(pk=MOVEMENT_BREAKFAST_ID)
        self.assertEqual(
            (movement.amount, movement.date, movement.reference), (Decimal("-90.00"), date(2026, 10, 1), "B-1")
        )

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the booked movement", {"id": MOVEMENT_BOOKED_ID}),
            # One booked movement among others: nothing is deleted.
            ("among others", {"id__in": [MOVEMENT_BOOKED_ID, MOVEMENT_BREAKFAST_ID]}),
        ]
    )
    def test_delete_refused(self, label, filters):
        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.delete)(filters)

        self.assertEqual(context.exception.code, "protected_error")
        self.assertEqual(AccountMovement.objects.filter(pk__in=[MOVEMENT_BOOKED_ID, MOVEMENT_BREAKFAST_ID]).count(), 2)
