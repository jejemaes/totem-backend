from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from account.models import Invoice

from account.tests.test_services.common_invoice import InvoiceServiceCommonMixin


class InvoiceModelTest(InvoiceServiceCommonMixin, TestCase):
    """ What `Invoice` holds on every write path: its number, its constraints, its
    payment status before any payment. """

    def test_number_follows_the_year(self):
        self.assertEqual(self.invoice_pipeweed.number, "INV/2026/00001")
        self.assertEqual(self.invoice_ale.number, "INV/2026/00002")

        invoices = Invoice.objects.bulk_create([
            self._invoice(date(2026, 1, 3)),
            self._invoice(date(2025, 12, 31)),
            self._invoice(date(2026, 11, 1)),
        ])
        # Each year counts on its own; within one, in the order of the batch.
        self.assertEqual(
            [i.number for i in invoices], ["INV/2026/00003", "INV/2025/00001", "INV/2026/00004"]
        )

    def test_number_on_save(self):
        # The admin writes through `save()`.
        invoice = self._invoice(date(2026, 2, 1))
        invoice.save()
        self.assertEqual(invoice.number, "INV/2026/00003")

    def test_number_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.objects.filter(pk=self.invoice_ale.pk).update(number=self.invoice_pipeweed.number)

    def test_amount_total_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Invoice.objects.filter(pk=self.invoice_ale.pk).update(amount_total=Decimal("0"))

    def test_unpaid(self):
        invoice = Invoice.objects.get(pk=self.invoice_pipeweed.pk)
        self.assertEqual(
            (invoice.amount_paid, invoice.amount_residual, invoice.payment_status),
            (Decimal("0"), Decimal("100.00"), "not_paid"),
        )

    # Utils

    def _invoice(self, day):
        return Invoice(
            date=day, contact=self.contact_tobold, account=self.account_shire, amount_total=Decimal("1"),
        )
