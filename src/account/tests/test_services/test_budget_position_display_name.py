from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.services import BudgetPositionService
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_budget import BUDGET_BAGEND_ID
from account.tests.test_services.common_budget_position import (
    POSITION_ALE_ID,
    POSITION_BREAKFAST_ID,
    POSITION_PIPEWEED_ID,
    POSITION_UNKNOWN_ID,
    BudgetPositionServiceCommonMixin,
)

OWN = ["budget_position_manage_own"]
ALL = ["budget_position_manage_all"]


class BudgetPositionDisplayNameServiceTest(BudgetPositionServiceCommonMixin, ServiceTestCaseMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetPositionService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the positions.
            ("one pk", [POSITION_ALE_ID], None, 2, [POSITION_ALE_ID]),
            ("in the order of the pks", [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], None, 2, [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]),
            ("a repeated pk appears once", [POSITION_ALE_ID, POSITION_ALE_ID], None, 2, [POSITION_ALE_ID]),
            ("an unknown pk is absent", [POSITION_UNKNOWN_ID, POSITION_ALE_ID], None, 2, [POSITION_ALE_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], None, 2, []),
            ("no pk", [], None, 0, []),
            # The path of the nested route narrows them further.
            ("narrowed by the filters", [POSITION_ALE_ID, POSITION_BREAKFAST_ID], {"budget_id": BUDGET_BAGEND_ID}, 2, [POSITION_BREAKFAST_ID]),
        ]
    )
    def test_display_name(self, label, pks, filters, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            positions = async_to_sync(self.service.display_name)(pks, ["id", "name", "color"], filters=filters)

        self.assertEqual([position.pk for position in positions], expected_pks)
        for position in positions:
            self.assertFalse({"name", "color"} & position.get_deferred_fields())
            self.assertIn("sequence", position.get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], [POSITION_BREAKFAST_ID, POSITION_ALE_ID]),
            ("own positions", OWN, [POSITION_BREAKFAST_ID]),
            ("all positions", ALL, [POSITION_BREAKFAST_ID, POSITION_ALE_ID]),
            ("both, combined with AND", OWN + ALL, [POSITION_BREAKFAST_ID]),
            ("anonymous: no role, no rule", None, [POSITION_BREAKFAST_ID, POSITION_ALE_ID]),
        ]
    )
    def test_display_name_access_rules(self, label, rules, expected_pks):
        if rules is None:
            service = self.get_service(BudgetPositionService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(BudgetPositionService, user=self.user_frodon)

        positions = async_to_sync(service.display_name)([POSITION_BREAKFAST_ID, POSITION_ALE_ID], ["id", "name"])

        self.assertEqual([position.pk for position in positions], expected_pks)
