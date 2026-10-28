from datetime import date
from decimal import Decimal

from account.models import (
    Account,
    AccountCategory,
    AccountMovement,
    Budget,
    BudgetLine,
    BudgetPosition,
)
from user.tests.test_api.common import CommonTestMixin as UserCommonTestMixin

ACCOUNT_ID1 = "01JA0000000000000000000001"
ACCOUNT_ID2 = "01JA0000000000000000000002"
ACCOUNT_ID3 = "01JA0000000000000000000003"

CATEGORY_GENERAL_ID = "01JC0000000000000000000001"
CATEGORY_SHIRE_ID = "01JC0000000000000000000002"
CATEGORY_BREE_ID = "01JC0000000000000000000003"

MOVEMENT_ID1 = "01JM0000000000000000000001"
MOVEMENT_ID2 = "01JM0000000000000000000002"
MOVEMENT_ID3 = "01JM0000000000000000000003"

BUDGET_ID1 = "01JB0000000000000000000001"
BUDGET_ID2 = "01JB0000000000000000000002"

POSITION_BREAKFAST_ID = "01JP0000000000000000000001"
POSITION_PIPEWEED_ID = "01JP0000000000000000000002"
POSITION_ALE_ID = "01JP0000000000000000000003"

LINE_BREAKFAST_ID = "01JN0000000000000000000001"
LINE_PIPEWEED_ID = "01JN0000000000000000000002"
LINE_ALE_ID = "01JN0000000000000000000003"

ACCOUNT_SCOPES = ["totem.account.create", "totem.account.read", "totem.account.update", "totem.account.delete"]
CATEGORY_SCOPES = [
    "totem.accountcategory.create",
    "totem.accountcategory.read",
    "totem.accountcategory.update",
    "totem.accountcategory.delete",
]
MOVEMENT_SCOPES = [
    "totem.accountmovement.create",
    "totem.accountmovement.read",
    "totem.accountmovement.update",
    "totem.accountmovement.delete",
]
BUDGET_SCOPES = ["totem.budget.create", "totem.budget.read", "totem.budget.update", "totem.budget.delete"]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class CommonTestMixin(UserCommonTestMixin):
    """ The ledger and the budgets every API test of `account` reads. Data only.

    On top of the users, `role` and API key of `user`:

        SHIRE  Bag End              +150.00  Mathom sale       (INV-001)
                                     -80.00  Second breakfast  [Second Breakfast]
                                     -20.50  Pipe-weed         [Pipe-weed]
        BREE   The Prancing Pony    no movement
        MORIA  Khazad-dum           inactive, no movement

    Categories: "Second Breakfast" (general, no account), "Pipe-weed" (SHIRE) and
    "Ale" (BREE).

    Budgets: BUDGET_ID1 "Bag End 2026" on SHIRE, in charge of Frodon, with a
    position on Second Breakfast (sequence 1) and one on Pipe-weed (sequence 2),
    one line each; BUDGET_ID2 "Prancing Pony 2026" on BREE, in charge of Gollum,
    with a position and a line on Ale. That split is what the `budget_*_manage_own`
    rules are tested against.

    Distinct from `account.tests.common`, which the service tests keep: the API
    tests own their data. The amounts are the same, so the totals are too.
    Everything is bulk created, so the stored totals are refreshed by hand, as a
    reconciliation job would.

    `role` is granted nothing here: each test class grants the scopes of its
    resource.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.account_shire, cls.account_bree, cls.account_moria = Account.objects.bulk_create([
            Account(id=ACCOUNT_ID1, code="SHIRE", name="Bag End"),
            Account(id=ACCOUNT_ID2, code="BREE", name="The Prancing Pony"),
            Account(id=ACCOUNT_ID3, code="MORIA", name="Khazad-dum", active=False),
        ])

        cls.category_general, cls.category_shire, cls.category_bree = AccountCategory.objects.bulk_create([
            AccountCategory(id=CATEGORY_GENERAL_ID, name="Second Breakfast"),
            AccountCategory(id=CATEGORY_SHIRE_ID, name="Pipe-weed", account=cls.account_shire),
            AccountCategory(id=CATEGORY_BREE_ID, name="Ale", account=cls.account_bree),
        ])

        cls.movement_sale, cls.movement_breakfast, cls.movement_pipeweed = AccountMovement.objects.bulk_create([
            AccountMovement(
                id=MOVEMENT_ID1, account=cls.account_shire, amount=Decimal("150.00"),
                name="Mathom sale", date=date(2026, 10, 15), reference="INV-001",
            ),
            AccountMovement(
                id=MOVEMENT_ID2, account=cls.account_shire, amount=Decimal("-80.00"),
                name="Second breakfast", date=date(2026, 10, 15), category=cls.category_general,
            ),
            AccountMovement(
                id=MOVEMENT_ID3, account=cls.account_shire, amount=Decimal("-20.50"),
                name="Pipe-weed", date=date(2026, 10, 15), category=cls.category_shire,
            ),
        ])
        Account.objects.refresh_computed()

        cls.budget_bagend, cls.budget_pony = Budget.objects.bulk_create([
            Budget(id=BUDGET_ID1, name="Bag End 2026", account=cls.account_shire, user=cls.user_frodon),
            Budget(id=BUDGET_ID2, name="Prancing Pony 2026", account=cls.account_bree, user=cls.user_gollum),
        ])
        cls.position_breakfast, cls.position_pipeweed, cls.position_ale = BudgetPosition.objects.bulk_create([
            BudgetPosition(
                id=POSITION_BREAKFAST_ID, budget=cls.budget_bagend, category=cls.category_general, sequence=1
            ),
            BudgetPosition(
                id=POSITION_PIPEWEED_ID, budget=cls.budget_bagend, category=cls.category_shire, sequence=2
            ),
            BudgetPosition(id=POSITION_ALE_ID, budget=cls.budget_pony, category=cls.category_bree),
        ])
        cls.line_breakfast, cls.line_pipeweed, cls.line_ale = BudgetLine.objects.bulk_create([
            BudgetLine(
                id=LINE_BREAKFAST_ID, name="Second breakfast", position=cls.position_breakfast,
                planned_amount=Decimal("-1000.00"),
            ),
            BudgetLine(
                id=LINE_PIPEWEED_ID, name="Pipe-weed", position=cls.position_pipeweed,
                planned_amount=Decimal("-300.00"),
            ),
            BudgetLine(
                id=LINE_ALE_ID, name="Ale", position=cls.position_ale, planned_amount=Decimal("-60.00"),
            ),
        ])
        # Refreshes the budget totals as well, which read the positions.
        BudgetPosition.objects.refresh_computed()
