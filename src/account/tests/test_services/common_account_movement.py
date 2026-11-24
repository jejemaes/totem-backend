from datetime import date
from decimal import Decimal

from account.models import Account, AccountMovement
from contact.models import Contact

from account.tests.test_services.common_account_category import AccountCategoryServiceCommonMixin

CONTACT_LOBELIA_ID = "01JK0000000000000000000001"
CONTACT_TOBOLD_ID = "01JK0000000000000000000002"

MOVEMENT_SALE_ID = "01JM0000000000000000000001"
MOVEMENT_BREAKFAST_ID = "01JM0000000000000000000002"
MOVEMENT_PIPEWEED_ID = "01JM0000000000000000000003"

MOVEMENT_UNKNOWN_ID = "01JM0000000000000000000099"

# The day of the ledger. The tests validating "not in the future" freeze today on
# it, as `NOW`.
LEDGER_DATE = date(2026, 10, 15)
NOW = "2026-10-15 10:00:00"


class AccountMovementServiceCommonMixin(AccountCategoryServiceCommonMixin):
    """ The ledger, on top of the accounts and categories:

        SHIRE  +150.00  Mathom sale       (INV-001)           <Lobelia>
               -80.00   Second breakfast  [Second Breakfast]
               -20.50   Pipe-weed         [Pipe-weed]         <Tobold>
        BREE   no movement
        MORIA  no movement

    All on `LEDGER_DATE`. SHIRE totals -100.50 debit, +150.00 credit, 49.50
    balance. Bulk created, so the stored totals are refreshed by hand, as a
    reconciliation job would. Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contact_lobelia, cls.contact_tobold = Contact.objects.bulk_create([
            Contact(id=CONTACT_LOBELIA_ID, first_name="Lobelia", last_name="Sackville-Baggins"),
            Contact(id=CONTACT_TOBOLD_ID, first_name="Tobold", last_name="Hornblower"),
        ])
        cls.movement_sale, cls.movement_breakfast, cls.movement_pipeweed = AccountMovement.objects.bulk_create([
            AccountMovement(
                id=MOVEMENT_SALE_ID, account=cls.account_shire, amount=Decimal("150.00"),
                name="Mathom sale", date=LEDGER_DATE, reference="INV-001", contact=cls.contact_lobelia,
            ),
            AccountMovement(
                id=MOVEMENT_BREAKFAST_ID, account=cls.account_shire, amount=Decimal("-80.00"),
                name="Second breakfast", date=LEDGER_DATE, category=cls.category_general,
            ),
            AccountMovement(
                id=MOVEMENT_PIPEWEED_ID, account=cls.account_shire, amount=Decimal("-20.50"),
                name="Pipe-weed", date=LEDGER_DATE, category=cls.category_shire, contact=cls.contact_tobold,
            ),
        ])
        Account.objects.refresh_computed()
