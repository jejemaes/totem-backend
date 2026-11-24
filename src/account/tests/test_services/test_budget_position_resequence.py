from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.models import BudgetPosition
from account.services import BudgetPositionService
from core.services.exceptions import ServiceValidationMultiError
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

# As the common data leaves them.
SEQUENCES = {POSITION_BREAKFAST_ID: 1, POSITION_PIPEWEED_ID: 2, POSITION_ALE_ID: 10}


class BudgetPositionResequenceServiceTest(BudgetPositionServiceCommonMixin, ServiceTestCaseMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetPositionService, user=self.user_frodon)

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the transaction, the rows found, then one UPDATE whatever
            # their number.
            ("a whole budget", [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], None, 0, 5, {POSITION_PIPEWEED_ID: 1, POSITION_BREAKFAST_ID: 2}),
            # Only the records given are numbered.
            ("a partial list", [POSITION_ALE_ID], None, 0, 5, {POSITION_ALE_ID: 1}),
            # A page further down a list is numbered where it sits.
            ("with an offset", [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], None, 20, 5, {POSITION_PIPEWEED_ID: 21, POSITION_BREAKFAST_ID: 22}),
            ("within the filters", [POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID], {"budget_id": BUDGET_BAGEND_ID}, 0, 5, {POSITION_PIPEWEED_ID: 1, POSITION_BREAKFAST_ID: 2}),
            ("no pk", [], None, 0, 0, {}),
        ]
    )
    def test_resequence(self, label, pks, filters, offset, query_count, expected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.resequence)(pks, filters=filters, offset=offset)

        self.assertEqual(count, len(pks))
        self.assertEqual(dict(BudgetPosition.objects.values_list("pk", "sequence")), {**SEQUENCES, **expected})

    @parameterized.expand(
        [
            # All or nothing, and none of these told apart: keyed on `ids`.
            # Refused before any query.
            ("a repeated pk", [POSITION_BREAKFAST_ID, POSITION_BREAKFAST_ID], None, 0),
            ("an unknown pk", [POSITION_BREAKFAST_ID, POSITION_UNKNOWN_ID], None, 5),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk", [POSITION_BREAKFAST_ID, "not-a-ulid"], None, 5),
            ("outside the filters", [POSITION_BREAKFAST_ID, POSITION_ALE_ID], {"budget_id": BUDGET_BAGEND_ID}, 5),
        ]
    )
    def test_resequence_invalid(self, label, pks, filters, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.resequence)(pks, filters=filters)

        self.assertEqual(list(ctx.exception.dict()), ["ids"])
        self.assertEqual(dict(BudgetPosition.objects.values_list("pk", "sequence")), SEQUENCES)

    @parameterized.expand(
        [
            # Reached through the *update* rules: numbering a record is updating it.
            ("no rule", [], None, True),
            ("own positions, another user's", OWN, None, False),
            ("all positions", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_resequence_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)
        pks = [POSITION_ALE_ID, POSITION_BREAKFAST_ID]

        if reached:
            self.assertEqual(async_to_sync(service.resequence)(pks), 2)
        else:
            # Out of reach reads as unknown: nothing is numbered.
            with self.assertRaises(ServiceValidationMultiError):
                async_to_sync(service.resequence)(pks)

        expected = {**SEQUENCES, POSITION_ALE_ID: 1, POSITION_BREAKFAST_ID: 2} if reached else SEQUENCES
        self.assertEqual(dict(BudgetPosition.objects.values_list("pk", "sequence")), expected)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def service_with_rules(self, rules, second_role_rules=None):
        """ The service acting as Frodon, whose role holds `rules`; with
        `second_role_rules`, Frodon holds a second role with those. `rules=None`
        is an anonymous caller. """
        if rules is None:
            return self.get_service(BudgetPositionService)
        self.role.rules = rules
        self.role.save()
        if second_role_rules is not None:
            self.role_hobbit.rules = second_role_rules
            self.role_hobbit.save()
            self.user_frodon.roles.add(self.role_hobbit)
        return self.get_service(BudgetPositionService, user=self.user_frodon)
