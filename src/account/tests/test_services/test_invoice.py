from datetime import date
from decimal import Decimal

from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Invoice
from account.schemas import InvoiceCreateSchema, InvoiceUpdateSchema
from account.services import InvoiceService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import MediaRootTestMixin, ServiceTestCaseMixin

from account.tests.test_services.common_account import ACCOUNT_BREE_ID
from account.tests.test_services.common_account_category import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
)
from account.tests.test_services.common_account_movement import CONTACT_TOBOLD_ID, NOW
from account.tests.test_services.common_invoice import (
    INVOICE_ALE_ID,
    INVOICE_PIPEWEED_ID,
    InvoiceServiceCommonMixin,
)


@freeze_time(NOW)
class InvoiceServiceTest(InvoiceServiceCommonMixin, MediaRootTestMixin, ServiceTestCaseMixin, TestCase):
    """ `InvoiceService`: the number, the file and its mimetype, the business
    rules.

    No access rules tests: no `BaseRule` is registered for `Invoice`.
    """

    payload_create = {
        "date": "2026-10-01",
        "contact": CONTACT_TOBOLD_ID,
        "account": ACCOUNT_BREE_ID,
        "amount_total": "12.50",
    }

    def setUp(self):
        super().setUp()
        self.service = self.get_service(InvoiceService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no file", None, None),
            ("a pdf", SimpleUploadedFile("bill.pdf", b"%PDF-1.4", content_type="application/pdf"), "application/pdf"),
            ("an image", SimpleUploadedFile("bill.png", b"\x89PNG", content_type="image/png"), "image/png"),
        ]
    )
    def test_create(self, label, upload, mimetype):
        [invoice] = async_to_sync(self.service.create)(
            [InvoiceCreateSchema(**self.payload_create, file_content=upload)]
        )

        invoice = Invoice.objects.get(pk=invoice.pk)
        self.assertEqual(invoice.number, "INV/2026/00003")
        self.assertEqual(invoice.file_mimetype, mimetype)
        self.assertEqual(bool(invoice.file_content), upload is not None)
        self.assertEqual(invoice.currency_code, "EUR")

    @parameterized.expand(
        [
            ("a text file", {"file_content": SimpleUploadedFile("bill.txt", b"owed")}, "file_content"),
            ("an svg", {"file_content": SimpleUploadedFile("bill.svg", b"<svg/>")}, "file_content"),
            ("in the future", {"date": "2026-10-16"}, "date"),
            ("a zero total", {"amount_total": "0"}, "amount_total"),
            ("a negative total", {"amount_total": "-1"}, "amount_total"),
            # The invoice is on BREE.
            ("a category of another account", {"category": CATEGORY_SHIRE_ID}, "category"),
        ]
    )
    def test_create_invalid(self, label, extra, field):
        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.create)([InvoiceCreateSchema(**{**self.payload_create, **extra})])

        self.assertEqual(list(context.exception.dict()[0]), [field])
        self.assertEqual(Invoice.objects.count(), 2)

    @parameterized.expand(
        [
            ("a general category", CATEGORY_GENERAL_ID),
            ("a category of its account", CATEGORY_BREE_ID),
        ]
    )
    def test_create_with_category(self, label, category_pk):
        [invoice] = async_to_sync(self.service.create)(
            [InvoiceCreateSchema(**self.payload_create, category=category_pk)]
        )

        self.assertEqual(Invoice.objects.get(pk=invoice.pk).category_id, category_pk)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_update(self):
        count, _queryset = async_to_sync(self.service.update)(
            {"id": INVOICE_ALE_ID}, InvoiceUpdateSchema(amount_total="30.00", due_date="2026-11-30")
        )

        self.assertEqual(count, 1)
        invoice = Invoice.objects.get(pk=INVOICE_ALE_ID)
        self.assertEqual((invoice.amount_total, invoice.due_date), (Decimal("30.00"), date(2026, 11, 30)))
        # The number is not written by an update.
        self.assertEqual(invoice.number, "INV/2026/00002")

    @parameterized.expand(
        [
            # Pipe-weed is on SHIRE, in the SHIRE category.
            ("a general category", {"category": CATEGORY_GENERAL_ID}, None),
            ("no category", {"category": None}, None),
            ("a category of another account", {"category": CATEGORY_BREE_ID}, "category"),
            # The category stays, the account changes under it.
            ("another account under its category", {"account": ACCOUNT_BREE_ID}, "category"),
            ("both together", {"account": ACCOUNT_BREE_ID, "category": CATEGORY_BREE_ID}, None),
        ]
    )
    def test_update_category(self, label, payload, error_field):
        before = Invoice.objects.values("account_id", "category_id").get(pk=INVOICE_PIPEWEED_ID)

        if error_field is None:
            async_to_sync(self.service.update)({"id": INVOICE_PIPEWEED_ID}, InvoiceUpdateSchema(**payload))
            after = Invoice.objects.values("account_id", "category_id").get(pk=INVOICE_PIPEWEED_ID)
            self.assertEqual(after, {**before, **{f"{name}_id": value for name, value in payload.items()}})
        else:
            with self.assertRaises(ServiceValidationMultiError) as context:
                async_to_sync(self.service.update)({"id": INVOICE_PIPEWEED_ID}, InvoiceUpdateSchema(**payload))
            self.assertEqual(list(context.exception.dict()[INVOICE_PIPEWEED_ID]), [error_field])
            self.assertEqual(Invoice.objects.values("account_id", "category_id").get(pk=INVOICE_PIPEWEED_ID), before)
