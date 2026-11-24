from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.services import BudgetService
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_budget import (
    BUDGET_BAGEND_ID,
    BUDGET_PONY_ID,
    BUDGET_UNKNOWN_ID,
    BudgetServiceCommonMixin,
)

OWN = ["budget_manage_own"]
ALL = ["budget_manage_all"]


class BudgetDisplayNameServiceTest(BudgetServiceCommonMixin, ServiceTestCaseMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the budgets.
            ("one pk", [BUDGET_PONY_ID], 2, [BUDGET_PONY_ID]),
            ("in the order of the pks", [BUDGET_PONY_ID, BUDGET_BAGEND_ID], 2, [BUDGET_PONY_ID, BUDGET_BAGEND_ID]),
            ("a repeated pk appears once", [BUDGET_PONY_ID, BUDGET_PONY_ID], 2, [BUDGET_PONY_ID]),
            ("an unknown pk is absent", [BUDGET_UNKNOWN_ID, BUDGET_PONY_ID], 2, [BUDGET_PONY_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            budgets = async_to_sync(self.service.display_name)(pks, ["id", "name"])

        self.assertEqual([budget.pk for budget in budgets], expected_pks)
        for budget in budgets:
            self.assertNotIn("name", budget.get_deferred_fields())
            self.assertIn("note", budget.get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], [BUDGET_BAGEND_ID, BUDGET_PONY_ID]),
            ("own budgets", OWN, [BUDGET_BAGEND_ID]),
            ("all budgets", ALL, [BUDGET_BAGEND_ID, BUDGET_PONY_ID]),
            ("both, combined with AND", OWN + ALL, [BUDGET_BAGEND_ID]),
            ("anonymous: no role, no rule", None, [BUDGET_BAGEND_ID, BUDGET_PONY_ID]),
        ]
    )
    def test_display_name_access_rules(self, label, rules, expected_pks):
        if rules is None:
            service = self.get_service(BudgetService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(BudgetService, user=self.user_frodon)

        budgets = async_to_sync(service.display_name)([BUDGET_BAGEND_ID, BUDGET_PONY_ID], ["id", "name"])

        # Out of reach and unknown are told apart by nothing: both are absent.
        self.assertEqual([budget.pk for budget in budgets], expected_pks)
