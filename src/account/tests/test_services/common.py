from decimal import Decimal

from django.utils import timezone

from account.models import Account, AccountCategory, AccountMovement
from user.models import User

USER_ID1 = "14041cce-8719-4637-92b1-51c4ade4b643"

ACCOUNT_ID1 = "01JA0000000000000000000001"
ACCOUNT_ID2 = "01JA0000000000000000000002"
ACCOUNT_ID3 = "01JA0000000000000000000003"

CATEGORY_GENERAL_ID = "01JC0000000000000000000001"
CATEGORY_SHOP_ID = "01JC0000000000000000000002"
CATEGORY_BANK_ID = "01JC0000000000000000000003"

MOVEMENT_ID1 = "01JM0000000000000000000001"
MOVEMENT_ID2 = "01JM0000000000000000000002"
MOVEMENT_ID3 = "01JM0000000000000000000003"


class AccountServiceTestMixin:
    """Two accounts, SHOP with three movements and BANK with none, ACCOUNT_ID3
    inactive; one general category and one per account.

    Created through the ORM, so the stored totals are refreshed by hand, as a
    reconciliation job would.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create(
            pk=USER_ID1,
            username="Tintin",
            password="MiL0u4ev3r",
            email="tintin@moulinsart.com",
        )

        cls.account_shop = Account.objects.create(id=ACCOUNT_ID1, code="SHOP", name="Shop")
        cls.account_bank = Account.objects.create(id=ACCOUNT_ID2, code="BANK", name="Bank")
        cls.account_old = Account.objects.create(
            id=ACCOUNT_ID3, code="OLD", name="Old shop", active=False
        )

        cls.category_general = AccountCategory.objects.create(id=CATEGORY_GENERAL_ID, name="Rent")
        cls.category_shop = AccountCategory.objects.create(
            id=CATEGORY_SHOP_ID, name="Stock", account=cls.account_shop
        )
        cls.category_bank = AccountCategory.objects.create(
            id=CATEGORY_BANK_ID, name="Fees", account=cls.account_bank
        )

        now = timezone.now()
        cls.movement_sale, cls.movement_rent, cls.movement_stock = AccountMovement.objects.bulk_create([
            AccountMovement(
                id=MOVEMENT_ID1, account=cls.account_shop, amount=Decimal("150.00"),
                name="Sale", date=now, reference="INV-001",
            ),
            AccountMovement(
                id=MOVEMENT_ID2, account=cls.account_shop, amount=Decimal("-80.00"),
                name="Rent", date=now, category=cls.category_general,
            ),
            AccountMovement(
                id=MOVEMENT_ID3, account=cls.account_shop, amount=Decimal("-20.50"),
                name="Stock", date=now, category=cls.category_shop,
            ),
        ])
        Account.objects.refresh_computed()

    def assertTotals(self, account_id, debit, credit, balance):
        account = Account.objects.get(pk=account_id)
        self.assertEqual(
            (account.total_debit, account.total_credit, account.balance),
            (Decimal(debit), Decimal(credit), Decimal(balance)),
        )
