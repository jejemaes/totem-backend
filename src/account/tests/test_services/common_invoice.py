from decimal import Decimal

from account.models import Invoice

from account.tests.test_services.common_account_movement import (
    LEDGER_DATE,
    AccountMovementServiceCommonMixin,
)

INVOICE_PIPEWEED_ID = "01JV0000000000000000000001"
INVOICE_ALE_ID = "01JV0000000000000000000002"


class InvoiceServiceCommonMixin(AccountMovementServiceCommonMixin):
    """ Two supplier invoices, on top of the ledger, both on `LEDGER_DATE`:

        INV/2026/00001  Tobold   SHIRE  100.00 EUR  (OLD-TOBY-7)  category SHIRE
        INV/2026/00002  Lobelia  BREE    40.00 USD                no category

    Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.invoice_pipeweed, cls.invoice_ale = Invoice.objects.bulk_create([
            Invoice(
                id=INVOICE_PIPEWEED_ID, reference="OLD-TOBY-7", date=LEDGER_DATE,
                contact=cls.contact_tobold, account=cls.account_shire, category=cls.category_shire,
                amount_total=Decimal("100.00"),
            ),
            Invoice(
                id=INVOICE_ALE_ID, date=LEDGER_DATE, contact=cls.contact_lobelia,
                account=cls.account_bree, amount_total=Decimal("40.00"), currency_code="USD",
            ),
        ])
