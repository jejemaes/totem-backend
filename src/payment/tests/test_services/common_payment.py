from payment.models import PaymentMethod

from account.tests.test_services.common_invoice import InvoiceServiceCommonMixin

METHOD_CASH_ID = "01JW0000000000000000000001"
METHOD_BANK_ID = "01JW0000000000000000000002"
METHOD_PIGEON_ID = "01JW0000000000000000000003"
# Valid ones, check digits and national key included.
IBAN_BANK = "FR7630006000011234567890189"
IBAN_OTHER = "DE89370400440532013000"


class PaymentServiceCommonMixin(InvoiceServiceCommonMixin):
    """ Three payment methods, on top of the ledger and the invoices of
    `account`: CASH, BANK and PIGEON (inactive). No payment: each test writes its
    own, through the service, so their movements are booked. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.method_cash, cls.method_bank, cls.method_pigeon = PaymentMethod.objects.bulk_create([
            PaymentMethod(id=METHOD_CASH_ID, sequence=1, code="CASH", name="Cash", type="cash"),
            PaymentMethod(id=METHOD_BANK_ID, sequence=2, code="BANK", name="Bank of Michel Delving", type="bank",
                iban=IBAN_BANK,
            ),
            PaymentMethod(
                id=METHOD_PIGEON_ID, sequence=3, code="PIGEON", name="Crebain", type="cash", active=False
            ),
        ])
