from decimal import Decimal

from account.models import Budget

from account.tests.test_services.common_account_movement import AccountMovementServiceCommonMixin

BUDGET_BAGEND_ID = "01JB0000000000000000000001"
BUDGET_PONY_ID = "01JB0000000000000000000002"

BUDGET_UNKNOWN_ID = "01JB0000000000000000000099"


class BudgetServiceCommonMixin(AccountMovementServiceCommonMixin):
    """ On top of the ledger: "Bag End 2026" on SHIRE, in charge of Frodon -- the
    acting user --, and "Prancing Pony 2026" on BREE, in charge of Gollum. That
    split is what the `budget_*_manage_own` rules are tested against. No position
    here: see `common_budget_position`. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.budget_bagend, cls.budget_pony = Budget.objects.bulk_create([
            Budget(id=BUDGET_BAGEND_ID, name="Bag End 2026", account=cls.account_shire, user=cls.user_frodon),
            Budget(id=BUDGET_PONY_ID, name="Prancing Pony 2026", account=cls.account_bree, user=cls.user_gollum),
        ])
        Budget.objects.refresh_computed()

    def assertBudgetTotals(self, budget_id, planned, practical):
        budget = Budget.objects.get(pk=budget_id)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount),
            (Decimal(planned), Decimal(practical)),
        )
