from decimal import Decimal

from account.models import BudgetLine, BudgetPosition

from account.tests.test_services.common_budget_position import BudgetPositionServiceCommonMixin

LINE_BREAKFAST_ID = "01JN0000000000000000000001"
LINE_PIPEWEED_ID = "01JN0000000000000000000002"
LINE_ALE_ID = "01JN0000000000000000000003"

LINE_UNKNOWN_ID = "01JN0000000000000000000099"


class BudgetLineServiceCommonMixin(BudgetPositionServiceCommonMixin):
    """ One line per position:

        Bag End 2026        Second Breakfast  -1000.00 planned  -80.00 practical
                            Pipe-weed          -300.00 planned  -20.50 practical
        Prancing Pony 2026  Ale                 -60.00 planned    0.00 practical

    Bag End totals -1300.00 planned, -100.50 practical. Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.line_breakfast, cls.line_pipeweed, cls.line_ale = BudgetLine.objects.bulk_create([
            BudgetLine(
                id=LINE_BREAKFAST_ID, name="Second breakfast", position=cls.position_breakfast,
                planned_amount=Decimal("-1000.00"), sequence=1,
            ),
            BudgetLine(
                id=LINE_PIPEWEED_ID, name="Pipe-weed", position=cls.position_pipeweed,
                planned_amount=Decimal("-300.00"), sequence=2,
            ),
            BudgetLine(id=LINE_ALE_ID, name="Ale", position=cls.position_ale, planned_amount=Decimal("-60.00")),
        ])
        BudgetPosition.objects.refresh_computed()
