from decimal import Decimal
from pathlib import Path

from django.core import serializers
from django.utils import timezone

from account.models import (
    Account,
    AccountCategory,
    AccountMovement,
    Budget,
    BudgetLine,
    BudgetPosition,
)
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


class AccountTestMixin:
    """Three accounts, SHOP with three movements, BANK and OLD (inactive) with
    none; one general category, and one for each of SHOP and BANK.

    Shared by the service and the API tests, which therefore describe the same
    ledger.

    Created through the ORM, so the stored totals are refreshed by hand, as a
    reconciliation job would.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create(  # the acting user of the service tests
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

        today = timezone.localdate()
        cls.movement_sale, cls.movement_rent, cls.movement_stock = AccountMovement.objects.bulk_create([
            AccountMovement(
                id=MOVEMENT_ID1, account=cls.account_shop, amount=Decimal("150.00"),
                name="Sale", date=today, reference="INV-001",
            ),
            AccountMovement(
                id=MOVEMENT_ID2, account=cls.account_shop, amount=Decimal("-80.00"),
                name="Rent", date=today, category=cls.category_general,
            ),
            AccountMovement(
                id=MOVEMENT_ID3, account=cls.account_shop, amount=Decimal("-20.50"),
                name="Stock", date=today, category=cls.category_shop,
            ),
        ])
        Account.objects.refresh_computed()

    def assertTotals(self, account_id, debit, credit, balance):
        account = Account.objects.get(pk=account_id)
        self.assertEqual(
            (account.total_debit, account.total_credit, account.balance),
            (Decimal(debit), Decimal(credit), Decimal(balance)),
        )


BUDGET_ID1 = "01JB0000000000000000000001"
BUDGET_ID2 = "01JB0000000000000000000002"

POSITION_RENT_ID = "01JP0000000000000000000001"
POSITION_STOCK_ID = "01JP0000000000000000000002"
POSITION_FEES_ID = "01JP0000000000000000000003"

LINE_RENT_ID = "01JL0000000000000000000001"
LINE_STOCK_ID = "01JL0000000000000000000002"
LINE_FEES_ID = "01JL0000000000000000000003"

USER_ID2 = "1fea2c88-abd2-4144-a71b-368b45671231"

ROLES_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "system" / "user_roles.json"


def load_roles(*pks):
    """The given roles, as `populate` loads them: read from the fixture of the app,
    so the tests exercise the permissions and rules actually shipped.

    Not `loaddata`: `user_roles` also names a fixture of the `website` app."""
    objects = [
        obj for obj in serializers.deserialize("json", ROLES_FIXTURE.read_text())
        if obj.object.pk in pks
    ]
    for obj in objects:
        obj.save()
    return {obj.object.pk: obj.object for obj in objects}


class BudgetTestMixin(AccountTestMixin):
    """On top of the ledger: BUDGET_ID1 on SHOP, in charge of `user` (Tintin), with
    a position on the general Rent and on SHOP's Stock, one line each; BUDGET_ID2
    on BANK, in charge of `other_user` (Haddock), with a position and a line on
    BANK's Fees. The three budget roles exist, granted to nobody."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_user = User.objects.create(
            pk=USER_ID2,
            username="Haddock",
            password="MiL0u4ev3r",
            email="haddock@moulinsart.com",
        )
        cls.roles = load_roles("BUDGET_READER", "BUDGET_USER", "BUDGET_ADMINISTRATOR")

        cls.budget_shop = Budget.objects.create(
            id=BUDGET_ID1, name="Shop 2026", account=cls.account_shop, user=cls.user
        )
        cls.budget_bank = Budget.objects.create(
            id=BUDGET_ID2, name="Bank 2026", account=cls.account_bank, user=cls.other_user
        )
        cls.position_rent, cls.position_stock, cls.position_fees = BudgetPosition.objects.bulk_create([
            BudgetPosition(id=POSITION_RENT_ID, budget=cls.budget_shop, category=cls.category_general, sequence=1),
            BudgetPosition(id=POSITION_STOCK_ID, budget=cls.budget_shop, category=cls.category_shop, sequence=2),
            BudgetPosition(id=POSITION_FEES_ID, budget=cls.budget_bank, category=cls.category_bank),
        ])
        cls.line_rent, cls.line_stock, cls.line_fees = BudgetLine.objects.bulk_create([
            BudgetLine(id=LINE_RENT_ID, name="Rent", position=cls.position_rent, planned_amount=Decimal("-1000.00")),
            BudgetLine(id=LINE_STOCK_ID, name="Restock", position=cls.position_stock, planned_amount=Decimal("-300.00")),
            BudgetLine(id=LINE_FEES_ID, name="Fees", position=cls.position_fees, planned_amount=Decimal("-60.00")),
        ])
        # Refreshes the budget totals as well, which read the positions.
        BudgetPosition.objects.refresh_computed()

    def grant(self, user, role_pk):
        user.roles.set([self.roles[role_pk]])

    def assertPositionTotals(self, position_id, planned, practical):
        position = BudgetPosition.objects.get(pk=position_id)
        self.assertEqual(
            (position.total_planned, position.total_practical), (Decimal(planned), Decimal(practical))
        )

    def assertBudgetTotals(self, budget_id, planned, practical):
        budget = Budget.objects.get(pk=budget_id)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount),
            (Decimal(planned), Decimal(practical)),
        )
