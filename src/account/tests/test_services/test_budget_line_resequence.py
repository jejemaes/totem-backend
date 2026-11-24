from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.models import BudgetLine
from account.services import BudgetLineService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_budget import BUDGET_BAGEND_ID
from account.tests.test_services.common_budget_line import (
    LINE_ALE_ID,
    LINE_BREAKFAST_ID,
    LINE_PIPEWEED_ID,
    LINE_UNKNOWN_ID,
    BudgetLineServiceCommonMixin,
)

OWN = ["budget_line_manage_own"]
ALL = ["budget_line_manage_all"]

# As the common data leaves them.
SEQUENCES = {LINE_BREAKFAST_ID: 1, LINE_PIPEWEED_ID: 2, LINE_ALE_ID: 10}


class BudgetLineResequenceServiceTest(BudgetLineServiceCommonMixin, ServiceTestCaseMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetLineService, user=self.user_frodon)

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the transaction, the rows found, then one UPDATE whatever
            # their number.
            ("a whole budget", [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], None, 0, 5, {LINE_PIPEWEED_ID: 1, LINE_BREAKFAST_ID: 2}),
            # Only the records given are numbered.
            ("a partial list", [LINE_ALE_ID], None, 0, 5, {LINE_ALE_ID: 1}),
            # A page further down a list is numbered where it sits.
            ("with an offset", [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], None, 20, 5, {LINE_PIPEWEED_ID: 21, LINE_BREAKFAST_ID: 22}),
            ("within the filters", [LINE_PIPEWEED_ID, LINE_BREAKFAST_ID], {"budget_id": BUDGET_BAGEND_ID}, 0, 5, {LINE_PIPEWEED_ID: 1, LINE_BREAKFAST_ID: 2}),
            ("no pk", [], None, 0, 0, {}),
        ]
    )
    def test_resequence(self, label, pks, filters, offset, query_count, expected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.resequence)(pks, filters=filters, offset=offset)

        self.assertEqual(count, len(pks))
        self.assertEqual(dict(BudgetLine.objects.values_list("pk", "sequence")), {**SEQUENCES, **expected})

    @parameterized.expand(
        [
            # All or nothing, and none of these told apart: keyed on `ids`.
            # Refused before any query.
            ("a repeated pk", [LINE_BREAKFAST_ID, LINE_BREAKFAST_ID], None, 0),
            ("an unknown pk", [LINE_BREAKFAST_ID, LINE_UNKNOWN_ID], None, 5),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk", [LINE_BREAKFAST_ID, "not-a-ulid"], None, 5),
            ("outside the filters", [LINE_BREAKFAST_ID, LINE_ALE_ID], {"budget_id": BUDGET_BAGEND_ID}, 5),
        ]
    )
    def test_resequence_invalid(self, label, pks, filters, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.resequence)(pks, filters=filters)

        self.assertEqual(list(ctx.exception.dict()), ["ids"])
        self.assertEqual(dict(BudgetLine.objects.values_list("pk", "sequence")), SEQUENCES)

    @parameterized.expand(
        [
            # Reached through the *update* rules: numbering a record is updating it.
            ("no rule", [], None, True),
            ("own lines, another user's", OWN, None, False),
            ("all lines", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_resequence_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)
        pks = [LINE_ALE_ID, LINE_BREAKFAST_ID]

        if reached:
            self.assertEqual(async_to_sync(service.resequence)(pks), 2)
        else:
            # Out of reach reads as unknown: nothing is numbered.
            with self.assertRaises(ServiceValidationMultiError):
                async_to_sync(service.resequence)(pks)

        expected = {**SEQUENCES, LINE_ALE_ID: 1, LINE_BREAKFAST_ID: 2} if reached else SEQUENCES
        self.assertEqual(dict(BudgetLine.objects.values_list("pk", "sequence")), expected)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def service_with_rules(self, rules, second_role_rules=None):
        """ The service acting as Frodon, whose role holds `rules`; with
        `second_role_rules`, Frodon holds a second role with those. `rules=None`
        is an anonymous caller. """
        if rules is None:
            return self.get_service(BudgetLineService)
        self.role.rules = rules
        self.role.save()
        if second_role_rules is not None:
            self.role_hobbit.rules = second_role_rules
            self.role_hobbit.save()
            self.user_frodon.roles.add(self.role_hobbit)
        return self.get_service(BudgetLineService, user=self.user_frodon)
