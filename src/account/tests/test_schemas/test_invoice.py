from django.test import SimpleTestCase

from account.schemas import InvoiceDisplayNameSchema
from payment.schemas import PaymentInvoiceTargetSchema


class InvoiceSchemaTest(SimpleTestCase):

    def test_payment_target_reads_the_display_name(self):
        # `payment` declares its own copy, as it cannot import ours: see
        # `PaymentInvoiceTargetSchema`. A field added here must be added there.
        self.assertEqual(
            list(PaymentInvoiceTargetSchema.model_fields), list(InvoiceDisplayNameSchema.model_fields)
        )
