from datetime import date, datetime, timezone as dt_timezone
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountMovement, Invoice
from account.schemas import AccountMovementUpdateSchema, InvoiceUpdateSchema
from account.services import AccountMovementService, InvoiceService
from core.schemas import ModelSchema
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from payment.models import Payment
from payment.schemas import PaymentCreateSchema
from payment.services import PaymentService

from account.tests.test_services.common_account import ACCOUNT_SHIRE_ID
from account.tests.test_services.common_account_category import CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID
from account.tests.test_services.common_account_movement import CONTACT_LOBELIA_ID, NOW
from account.tests.test_services.common_invoice import INVOICE_ALE_ID, INVOICE_PIPEWEED_ID
from payment.tests.test_services.common_payment import METHOD_BANK_ID, PaymentServiceCommonMixin

NOW_DATETIME = datetime(2026, 10, 15, 10, 0, tzinfo=dt_timezone.utc)

# SHIRE before any payment: the ledger of `common_account_movement`.
SHIRE_TOTALS = ("-100.50", "150.00", "49.50")


class PaymentInput(ModelSchema):
    """The payment fields a document's routes accept: the target ones are
    forced by `payment_register`. Any schema will do for the service; this one
    stands for the API's, declared in `account.schemas` with the routes."""

    class Meta:
        model = Payment
        fields = ["date", "amount", "currency_code", "direction", "payment_method", "reference"]
        optional_fields = "__all__"


@freeze_time(NOW)
class InvoicePaymentServiceTest(PaymentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ The payments of an invoice, through `InvoiceService.payment_read`,
    `payment_register`, `payment_update` and `payment_cancel`: done payments
    only, the rules of a supplier invoice, and the account movement each books -- with what follows from it: the
    paid amount and status of the invoice, the totals of its account.

    No access rules tests: no `BaseRule` is registered for `Invoice` nor
    `Payment`.
    """

    payload = {"date": "2026-10-10", "amount": "30.00", "payment_method": METHOD_BANK_ID, "reference": "TRF-1"}

    def setUp(self):
        super().setUp()
        self.service = self.get_service(InvoiceService, user=self.user_frodon)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    def test_read(self):
        with freeze_time("2026-10-14 08:00:00"):
            first = self._register()
        second = self._register(reference="TRF-2")
        # Another invoice's, and one of this invoice not done: not listed.
        self._register(invoice_pk=INVOICE_ALE_ID, amount="5.00")
        self._payment_not_done()

        queryset = async_to_sync(self.service.payment_read)(INVOICE_PIPEWEED_ID)

        # The latest first: same date, created later.
        self.assertEqual(list(queryset.values_list("pk", flat=True)), [second.pk, first.pk])

    def test_read_unknown_invoice(self):
        with self.assertRaises(Invoice.DoesNotExist):
            async_to_sync(self.service.payment_read)("01JV0000000000000000000099")

    # ------------------------------------------
    # Register
    # ------------------------------------------

    def test_register_defaults_from_the_invoice(self):
        payment = self._register()

        payment = Payment.objects.get(pk=payment.pk)
        self.assertEqual(
            (payment.target_type, payment.invoice_id, payment.direction, payment.currency_code, payment.contact_id),
            ("invoice", INVOICE_PIPEWEED_ID, "outgoing", "EUR", self.contact_tobold.pk),
        )
        # Registered done, whatever the input.
        self.assertEqual((payment.state, payment.done_date), ("done", NOW_DATETIME))

    def test_register_books_a_movement(self):
        payment = self._register()

        movement = Payment.objects.get(pk=payment.pk).account_movement
        self.assertEqual(
            (
                movement.account_id, movement.amount, movement.date, movement.name, movement.reference,
                movement.contact_id, movement.category_id, movement.origin_type, movement.invoice_id,
            ),
            (
                ACCOUNT_SHIRE_ID, Decimal("-30.00"), date(2026, 10, 10), "Payment TRF-1 - INV/2026/00001",
                # The default category of the invoice.
                "INV/2026/00001", self.contact_tobold.pk, CATEGORY_SHIRE_ID, "invoice", INVOICE_PIPEWEED_ID,
            ),
        )
        self.assertInvoice(INVOICE_PIPEWEED_ID, "30.00", "70.00", "partially_paid")
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, "-130.50", "150.00", "19.50")

    def test_register_partial_payments(self):
        self._register()
        self.assertInvoice(INVOICE_PIPEWEED_ID, "30.00", "70.00", "partially_paid")

        self._register(amount="70.00", reference="TRF-2")
        self.assertInvoice(INVOICE_PIPEWEED_ID, "100.00", "0.00", "paid")
        self.assertEqual(AccountMovement.objects.filter(invoice_id=INVOICE_PIPEWEED_ID).count(), 2)
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, "-200.50", "150.00", "-50.50")

    @parameterized.expand(
        [
            ("an incoming payment", {"direction": "incoming"}, ["direction"]),
            ("another currency", {"currency_code": "USD"}, ["currency_code"]),
            ("more than due", {"amount": "100.01"}, ["amount"]),
        ]
    )
    def test_register_invalid(self, label, extra, fields):
        with self.assertRaises(ServiceValidationMultiError) as context:
            self._register(**extra)

        self.assertEqual(list(context.exception.dict()[0]), fields)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(AccountMovement.objects.filter(origin_type__isnull=False).exists())

    def test_register_in_the_currency_of_the_invoice(self):
        # ALE is in USD: the default follows it.
        payment = self._register(invoice_pk=INVOICE_ALE_ID, amount="10.00")
        self.assertEqual(Payment.objects.get(pk=payment.pk).currency_code, "USD")

    def test_register_unknown_invoice(self):
        with self.assertRaises(Invoice.DoesNotExist):
            self._register(invoice_pk="01JV0000000000000000000099")
        self.assertFalse(Payment.objects.exists())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_update_payment_not_done(self):
        # Out of reach here, whoever wrote it: only the done payments are.
        payment = self._payment_not_done()

        count, _queryset = self._update(payment.pk, amount="1.00")

        self.assertEqual(count, 0)
        self.assertEqual(Payment.objects.get(pk=payment.pk).amount, Decimal("30.00"))

    def test_update_rewrites_the_movement(self):
        payment = self._register()
        movement_id = Payment.objects.get(pk=payment.pk).account_movement_id

        self._update(payment.pk, amount="45.00", date="2026-10-12", reference="TRF-1b")

        # The name, written at booking, is the movement's own since.
        movement = AccountMovement.objects.get(pk=movement_id)
        self.assertEqual(
            (movement.amount, movement.date, movement.name),
            (Decimal("-45.00"), date(2026, 10, 12), "Payment TRF-1 - INV/2026/00001"),
        )
        self.assertInvoice(INVOICE_PIPEWEED_ID, "45.00", "55.00", "partially_paid")
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, "-145.50", "150.00", "4.50")

    def test_update_its_own_share_is_due_again(self):
        # 30 already paid by this payment: it may grow to the whole 100.
        payment = self._register()
        self._update(payment.pk, amount="100.00")
        self.assertInvoice(INVOICE_PIPEWEED_ID, "100.00", "0.00", "paid")

        with self.assertRaises(ServiceValidationMultiError) as context:
            self._update(payment.pk, amount="100.01")
        self.assertEqual(list(context.exception.dict()[payment.pk]), ["amount"])

    def test_update_payment_of_another_invoice(self):
        # Filtered on the invoice of the path: the payment is not found there.
        payment = self._register()

        count, _queryset = self._update(payment.pk, invoice_pk=INVOICE_ALE_ID, amount="1.00")

        self.assertEqual(count, 0)
        self.assertEqual(Payment.objects.get(pk=payment.pk).amount, Decimal("30.00"))

    # ------------------------------------------
    # Cancel
    # ------------------------------------------

    def test_cancel(self):
        payment = self._register()
        movement_id = Payment.objects.get(pk=payment.pk).account_movement_id

        self.assertEqual(async_to_sync(self.service.payment_cancel)(INVOICE_PIPEWEED_ID, payment.pk), 1)

        # Kept, as a trace, but cancelled: its movement goes, the invoice drops back.
        payment = Payment.objects.get(pk=payment.pk)
        self.assertEqual((payment.state, payment.done_date, payment.account_movement_id), ("cancelled", None, None))
        self.assertFalse(AccountMovement.objects.filter(pk=movement_id).exists())
        self.assertInvoice(INVOICE_PIPEWEED_ID, "0", "100.00", "not_paid")
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, *SHIRE_TOTALS)
        # And out of the invoice's payments.
        self.assertFalse(async_to_sync(self.service.payment_read)(INVOICE_PIPEWEED_ID).exists())

    @parameterized.expand([("of another invoice", INVOICE_ALE_ID, True), ("not done", INVOICE_PIPEWEED_ID, False)])
    def test_cancel_out_of_reach(self, label, invoice_pk, done):
        payment = self._register() if done else self._payment_not_done()
        state = Payment.objects.get(pk=payment.pk).state

        self.assertEqual(async_to_sync(self.service.payment_cancel)(invoice_pk, payment.pk), 0)

        self.assertEqual(Payment.objects.get(pk=payment.pk).state, state)

    # ------------------------------------------
    # The booked movement, and the invoice
    # ------------------------------------------

    def test_booked_movement_keeps_its_edits(self):
        # Its name, contact and category are the movement's once booked: a later
        # write of the payment rewrites what the payment owns, and leaves them be.
        payment = self._register()
        movement_id = Payment.objects.get(pk=payment.pk).account_movement_id
        movement_service = self.get_service(AccountMovementService, user=self.user_frodon)
        async_to_sync(movement_service.update)(
            {"id": movement_id},
            AccountMovementUpdateSchema(
                name="Old Toby, autumn", contact=CONTACT_LOBELIA_ID, category=CATEGORY_GENERAL_ID
            ),
        )

        self._update(payment.pk, amount="45.00", reference="TRF-1b")

        movement = AccountMovement.objects.get(pk=movement_id)
        self.assertEqual(
            (movement.name, movement.contact_id, movement.category_id, movement.amount),
            ("Old Toby, autumn", CONTACT_LOBELIA_ID, CATEGORY_GENERAL_ID, Decimal("-45.00")),
        )

    def test_booked_movement_keeps_its_category(self):
        # The default of the invoice applies to the movements booked from then on:
        # one already booked keeps the category it has.
        payment = self._register()
        invoice_service = self.get_service(InvoiceService, user=self.user_frodon)
        async_to_sync(invoice_service.update)(
            {"id": INVOICE_PIPEWEED_ID}, InvoiceUpdateSchema(category=CATEGORY_GENERAL_ID)
        )
        self._update(payment.pk, amount="45.00")
        second = self._register(amount="10.00", reference="TRF-2")

        self.assertEqual(Payment.objects.get(pk=payment.pk).account_movement.category_id, CATEGORY_SHIRE_ID)
        self.assertEqual(Payment.objects.get(pk=second.pk).account_movement.category_id, CATEGORY_GENERAL_ID)

    def test_invoice_with_payments_is_protected(self):
        self._register()

        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.delete)({"id": INVOICE_PIPEWEED_ID})
        self.assertEqual(context.exception.code, "protected_error")

    # Utils

    def _register(self, invoice_pk=INVOICE_PIPEWEED_ID, **extra):
        return async_to_sync(self.service.payment_register)(invoice_pk, PaymentInput(**{**self.payload, **extra}))

    def _payment_not_done(self):
        """A pending payment of the invoice, written past its routes."""
        [payment] = async_to_sync(self.get_service(PaymentService, user=self.user_frodon).create)([
            PaymentCreateSchema(
                **self.payload, direction="outgoing", state="pending", target_type="invoice",
                invoice=INVOICE_PIPEWEED_ID,
            )
        ])
        return payment

    def _update(self, pk, invoice_pk=INVOICE_PIPEWEED_ID, **values):
        return async_to_sync(self.service.payment_update)(invoice_pk, pk, PaymentInput(**values))

    def assertInvoice(self, pk, paid, residual, status):
        invoice = Invoice.objects.get(pk=pk)
        self.assertEqual(
            (invoice.amount_paid, invoice.amount_residual, invoice.payment_status),
            (Decimal(paid), Decimal(residual), status),
        )
