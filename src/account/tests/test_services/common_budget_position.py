from decimal import Decimal

from account.models import BudgetPosition

from account.tests.test_services.common_budget import BudgetServiceCommonMixin

POSITION_BREAKFAST_ID = "01JP0000000000000000000001"
POSITION_PIPEWEED_ID = "01JP0000000000000000000002"
POSITION_ALE_ID = "01JP0000000000000000000003"

POSITION_UNKNOWN_ID = "01JP0000000000000000000099"


class BudgetPositionServiceCommonMixin(BudgetServiceCommonMixin):
    """ On top of the budgets: Bag End has a position on Second Breakfast
    (sequence 1) and one on Pipe-weed (sequence 2), the Prancing Pony one on Ale.
    No line here: see `common_budget_line`. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.position_breakfast, cls.position_pipeweed, cls.position_ale = BudgetPosition.objects.bulk_create([
            BudgetPosition(id=POSITION_BREAKFAST_ID, budget=cls.budget_bagend, category=cls.category_general, sequence=1),
            BudgetPosition(id=POSITION_PIPEWEED_ID, budget=cls.budget_bagend, category=cls.category_shire, sequence=2),
            BudgetPosition(id=POSITION_ALE_ID, budget=cls.budget_pony, category=cls.category_bree),
        ])
        # Refreshes the budget totals as well, which read the positions.
        BudgetPosition.objects.refresh_computed()

    def assertPositionTotals(self, position_id, planned, practical):
        position = BudgetPosition.objects.get(pk=position_id)
        self.assertEqual(
            (position.total_planned, position.total_practical), (Decimal(planned), Decimal(practical))
        )
