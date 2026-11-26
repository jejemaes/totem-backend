from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Invoice
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from payment.models import Payment
from payment.schemas import PaymentCreateSchema, PaymentUpdateSchema
from payment.services import PaymentService
from payment.services.mixins import payment_target_registry

from account.services import InvoiceService
from account.tests.test_services.common_account import ACCOUNT_SHIRE_ID
from account.tests.test_services.common_account_movement import NOW
from account.tests.test_services.common_invoice import INVOICE_PIPEWEED_ID
from payment.tests.test_services.common_payment import (
    METHOD_BANK_ID,
    METHOD_PIGEON_ID,
    PaymentServiceCommonMixin,
)

NOW_DATETIME = datetime(2026, 10, 15, 10, 0, tzinfo=dt_timezone.utc)
METHOD_UNKNOWN_ID = "01JW0000000000000000000099"
PAYMENT_UNKNOWN_ID = "01JX0000000000000000000099"


@freeze_time(NOW)
class PaymentServiceTest(PaymentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `PaymentService`, whatever the document: the target and its constraint,
    the movement it books, the date a payment is done, the states that can be
    deleted. The rules of a
    kind of document are its service's: an invoice's are tested in `account`
    (`test_invoice_payment`).

    No access rules tests: no `BaseRule` is registered for `Payment`.
    """

    payload_create = {
        "date": "2026-10-10",
        "amount": "30.00",
        "direction": "outgoing",
        "payment_method": METHOD_BANK_ID,
        "reference": "TRF-1",
    }

    def setUp(self):
        super().setUp()
        self.service = self.get_service(PaymentService, user=self.user_frodon)

    # ------------------------------------------
    # Target registry
    # ------------------------------------------

    def test_invoice_is_settled_by_its_service(self):
        self.assertIs(payment_target_registry["invoice"], InvoiceService)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # Settling no document: no movement, even done.
            ("a draft", {}, "draft", None, None),
            ("done, settling nothing", {"state": "done"}, "done", NOW_DATETIME, None),
            # Settling an invoice, done: the movement the invoice describes.
            (
                "done, settling an invoice",
                {"state": "done", "target_type": "invoice", "invoice": INVOICE_PIPEWEED_ID},
                "done", NOW_DATETIME, ACCOUNT_SHIRE_ID,
            ),
            # Not done: nothing paid yet, nothing booked.
            (
                "pending, settling an invoice",
                {"state": "pending", "target_type": "invoice", "invoice": INVOICE_PIPEWEED_ID},
                "pending", None, None,
            ),
        ]
    )
    def test_create(self, label, extra, state, done_date, movement_account_pk):
        [payment] = self._create(**extra)

        payment = Payment.objects.select_related("account_movement").get(pk=payment.pk)
        self.assertEqual((payment.state, payment.done_date), (state, done_date))
        self.assertEqual(
            payment.account_movement.account_id if payment.account_movement else None, movement_account_pk
        )
        paid = "30.00" if movement_account_pk else "0.00"
        self.assertEqual(Invoice.objects.get(pk=INVOICE_PIPEWEED_ID).amount_paid, Decimal(paid))

    @parameterized.expand(
        [
            ("an invoice without target type", {"invoice": INVOICE_PIPEWEED_ID}, ["invoice"]),
            ("a target type without invoice", {"target_type": "invoice"}, ["invoice"]),
            ("a zero amount", {"amount": "0"}, ["amount"]),
            ("an inactive method", {"payment_method": METHOD_PIGEON_ID}, ["payment_method"]),
            # The rules of the invoice, told by its service: see `test_invoice_payment`.
            (
                "an incoming payment of an invoice",
                {"direction": "incoming", "target_type": "invoice", "invoice": INVOICE_PIPEWEED_ID},
                ["direction"],
            ),
            (
                "beyond what the invoice is due",
                {"state": "done", "amount": "100.01", "target_type": "invoice", "invoice": INVOICE_PIPEWEED_ID},
                ["amount"],
            ),
        ]
    )
    def test_create_invalid(self, label, extra, fields):
        with self.assertRaises(ServiceValidationMultiError) as context:
            self._create(**extra)

        self.assertEqual(list(context.exception.dict()[0]), fields)
        self.assertFalse(Payment.objects.exists())

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([self.payload_create])

        self.assertFalse(Payment.objects.exists())

    @parameterized.expand(
        [
            ("unknown method", {"payment_method": METHOD_UNKNOWN_ID}, "payment_method"),
            ("unknown contact", {"contact": "01JK0000000000000000000099"}, "contact"),
            ("unknown invoice", {"target_type": "invoice", "invoice": "01JV0000000000000000000099"}, "invoice"),
        ]
    )
    def test_create_relations(self, label, extra, error_key):
        with self.assertRaises(ServiceValidationMultiError) as context:
            self._create(**extra)

        self.assertEqual(list(context.exception.dict()[0]), [error_key])
        self.assertFalse(Payment.objects.exists())

    def test_create_batch(self):
        # All or nothing: the valid inputs are not written either, and the error
        # is keyed by the position of the input.
        data = [
            PaymentCreateSchema(**{**self.payload_create, **extra})
            for extra in ({}, {"amount": "0"}, {"state": "done"})
        ]

        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.create)(data)

        self.assertEqual({key: list(value) for key, value in context.exception.dict().items()}, {1: ["amount"]})
        self.assertFalse(Payment.objects.exists())

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(["state", "direction", "currency_code"])

        # No default direction: who pays whom is the payment's to say.
        self.assertEqual(values, {"state": "draft", "currency_code": "EUR"})

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ["draft", "done", "invoice"]),
            ("done", {"state": "done"}, ["done", "invoice"]),
            ("of an invoice", {"invoice": INVOICE_PIPEWEED_ID}, ["invoice"]),
            ("settling nothing", {"target_type__isnull": True}, ["draft", "done"]),
        ]
    )
    def test_read_filters(self, label, filters, expected):
        pks = self._create_three()

        payments = async_to_sync(self.service.read)(filters)

        self.assertCountEqual([payment.pk for payment in payments], [pks[name] for name in expected])

    @parameterized.expand(
        [
            ("by amount", ["amount"], ["done", "invoice", "draft"]),
            ("by date, descending", ["-date"], ["invoice", "done", "draft"]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected):
        pks = self._create_three()

        payments = async_to_sync(self.service.read)(ordering=ordering)

        self.assertEqual([payment.pk for payment in payments], [pks[name] for name in expected])

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            # The movement follows the payment: booked when it is done...
            ("done", "draft", {"state": "done"}, Decimal("-30.00")),
            # ...rewritten with it...
            ("a new amount", "done", {"amount": "45.00"}, Decimal("-45.00")),
            # ...taken back when it no longer is.
            ("cancelled", "done", {"state": "cancelled"}, None),
        ]
    )
    def test_update(self, label, state, payload, movement_amount):
        [payment] = self._create(state=state, target_type="invoice", invoice=INVOICE_PIPEWEED_ID)

        count, queryset = async_to_sync(self.service.update)({"id": payment.pk}, PaymentUpdateSchema(**payload))

        self.assertEqual((count, [p.pk for p in queryset]), (1, [payment.pk]))
        payment = Payment.objects.select_related("account_movement").get(pk=payment.pk)
        self.assertEqual(payment.account_movement.amount if payment.account_movement else None, movement_amount)
        self.assertEqual(
            Invoice.objects.get(pk=INVOICE_PIPEWEED_ID).amount_paid, -(movement_amount or Decimal("0"))
        )

    def test_update_partial(self):
        [payment] = self._create()

        async_to_sync(self.service.update)({"id": payment.pk}, PaymentUpdateSchema(reference="TRF-1b"))

        payment = Payment.objects.get(pk=payment.pk)
        self.assertEqual((payment.reference, payment.amount, payment.state), ("TRF-1b", Decimal("30.00"), "draft"))

    @parameterized.expand(
        [
            ("a zero amount", {"amount": "0"}, ["amount"]),
            ("an invoice without target type", {"invoice": INVOICE_PIPEWEED_ID}, ["invoice"]),
            ("an inactive method", {"payment_method": METHOD_PIGEON_ID}, ["payment_method"]),
        ]
    )
    def test_update_invalid(self, label, payload, fields):
        [payment] = self._create()

        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.update)({"id": payment.pk}, PaymentUpdateSchema(**payload))

        # `validate_data` keys by the record, a relation refused before by its index.
        [errors] = context.exception.dict().values()
        self.assertEqual(list(errors), fields)
        self.assertEqual(Payment.objects.get(pk=payment.pk).amount, Decimal("30.00"))

    def test_update_refuses_a_dict(self):
        [payment] = self._create()

        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": payment.pk}, {"amount": "1"})

        self.assertEqual(Payment.objects.get(pk=payment.pk).amount, Decimal("30.00"))

    def test_update_done_date(self):
        with freeze_time("2026-10-01 08:00:00"):
            [payment] = self._create(state="done")

        # Done again: keeps the date it was first marked so.
        async_to_sync(self.service.update)({"id": payment.pk}, PaymentUpdateSchema(state="done"))
        payment.refresh_from_db()
        self.assertEqual(payment.done_date, datetime(2026, 10, 1, 8, 0, tzinfo=dt_timezone.utc))

        # Leaving done clears it.
        async_to_sync(self.service.update)({"id": payment.pk}, PaymentUpdateSchema(state="cancelled"))
        payment.refresh_from_db()
        self.assertIsNone(payment.done_date)

    def test_update_not_found(self):
        count, queryset = async_to_sync(self.service.update)(
            {"id": PAYMENT_UNKNOWN_ID}, PaymentUpdateSchema(reference="TRF-9")
        )

        self.assertEqual((count, list(queryset)), (0, []))

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand([("draft", "draft"), ("cancelled", "cancelled")])
    def test_delete(self, label, state):
        [payment] = self._create(state=state)
        self.assertEqual(async_to_sync(self.service.delete)({"id": payment.pk}), 1)
        self.assertFalse(Payment.objects.exists())

    @parameterized.expand([("pending", "pending"), ("done", "done")])
    def test_delete_refused(self, label, state):
        [payment] = self._create(state=state)
        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.delete)({"id": payment.pk})
        self.assertEqual(context.exception.code, "protected_error")
        self.assertEqual(Payment.objects.get(pk=payment.pk).amount, Decimal("30.00"))

    def test_delete_not_found(self):
        self.assertEqual(async_to_sync(self.service.delete)({"id": PAYMENT_UNKNOWN_ID}), 0)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _create(self, **extra):
        return async_to_sync(self.service.create)([PaymentCreateSchema(**{**self.payload_create, **extra})])

    def _create_three(self):
        """A draft of 30.00 on 2026-10-08, a done one of 10.00 on 2026-10-09,
        and a done one of 20.00 on 2026-10-10 paying Pipe-weed: their pks by name."""
        [draft] = self._create(date="2026-10-08")
        [done] = self._create(date="2026-10-09", amount="10.00", state="done")
        [invoice] = self._create(
            amount="20.00", state="done", target_type="invoice", invoice=INVOICE_PIPEWEED_ID
        )
        return {"draft": draft.pk, "done": done.pk, "invoice": invoice.pk}
