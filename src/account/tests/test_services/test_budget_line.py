from decimal import Decimal

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from parameterized import parameterized

from account.models import BudgetLine
from account.schemas import BudgetLineCreateSchema, BudgetLineUpdateSchema
from account.services import BudgetLineService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_budget import BUDGET_BAGEND_ID, BUDGET_PONY_ID, BUDGET_UNKNOWN_ID
from account.tests.test_services.common_budget_line import (
    LINE_ALE_ID,
    LINE_BREAKFAST_ID,
    LINE_PIPEWEED_ID,
    LINE_UNKNOWN_ID,
    BudgetLineServiceCommonMixin,
)
from account.tests.test_services.common_budget_position import (
    POSITION_ALE_ID,
    POSITION_BREAKFAST_ID,
    POSITION_PIPEWEED_ID,
    POSITION_UNKNOWN_ID,
)

ALL_LINE_IDS = [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID, LINE_ALE_ID]

OWN = ["budget_line_manage_own"]
ALL = ["budget_line_manage_all"]


class BudgetLineServiceTest(BudgetLineServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `BudgetLineService`: create, read, update, delete. The budget of a line is
    derived from its position by the QuerySet; every write refreshes the planned
    totals of the positions and budgets it touches. """

    payload_create = {"budget": BUDGET_BAGEND_ID, "position": POSITION_BREAKFAST_ID, "name": "Mushrooms", "planned_amount": "-500"}

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetLineService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("required fields only", {}, {"sequence": 10}, ("-1500.00", "-300.00"), "-1800.00"),
            ("with a sequence", {"sequence": 5}, {"sequence": 5}, ("-1500.00", "-300.00"), "-1800.00"),
            ("on the other position", {"position": POSITION_PIPEWEED_ID}, {"position_id": POSITION_PIPEWEED_ID}, ("-1000.00", "-800.00"), "-1800.00"),
        ]
    )
    def test_create(self, label, values, expected_values, position_planned, budget_planned):
        # The roles, the budget and the position, the insert, then the refresh of
        # the totals of the position and of its budget.
        with self.assertNumQueries(10):
            instances = async_to_sync(self.service.create)([BudgetLineCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual([line.name for line in instances], ["Mushrooms"])
        line = BudgetLine.objects.get(pk=instances[0].pk)
        self.assertEqual((line.budget_id, line.planned_amount), (BUDGET_BAGEND_ID, Decimal("-500.00")))
        self.assertEqual({name: getattr(line, name) for name in expected_values}, expected_values)
        self.assertPositionTotals(POSITION_BREAKFAST_ID, position_planned[0], "-80.00")
        self.assertPositionTotals(POSITION_PIPEWEED_ID, position_planned[1], "-20.50")
        self.assertBudgetTotals(BUDGET_BAGEND_ID, budget_planned, "-100.50")

    @parameterized.expand(
        [
            # `validate_data`: the budget named must be the position's.
            ("a position of another budget", {"position": POSITION_ALE_ID}, 6, "position"),
        ]
    )
    def test_create_invalid(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([BudgetLineCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(BudgetLine.objects.count(), 3)
        self.assertBudgetTotals(BUDGET_BAGEND_ID, "-1300.00", "-100.50")

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([self.payload_create])

        self.assertEqual(BudgetLine.objects.count(), 3)

    @parameterized.expand(
        [
            ("unknown position", {"position": POSITION_UNKNOWN_ID}, "position"),
            ("unknown budget", {"budget": BUDGET_UNKNOWN_ID}, "budget"),
        ]
    )
    def test_create_relations(self, label, values, error_key):
        with self.assertNumQueries(3):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([BudgetLineCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(BudgetLine.objects.count(), 3)

    @parameterized.expand(
        [
            # Each budget touched is refreshed once.
            (
                "every input valid",
                [{"planned_amount": "-1"}, {"position": POSITION_PIPEWEED_ID, "planned_amount": "-2"}, {"budget": BUDGET_PONY_ID, "position": POSITION_ALE_ID, "planned_amount": "-3"}],
                10,
                None,
                ("-1303.00", "-63.00"),
            ),
            (
                "the second input invalid",
                [{"planned_amount": "-1"}, {"position": POSITION_ALE_ID}],
                6,
                {1: ["position"]},
                ("-1300.00", "-60.00"),
            ),
        ]
    )
    def test_create_batch(self, label, values_list, query_count, errors, budget_planned):
        data = [BudgetLineCreateSchema(**{**self.payload_create, **values}) for values in values_list]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual(len(instances), 3)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertEqual(BudgetLine.objects.count(), 3)
        self.assertBudgetTotals(BUDGET_BAGEND_ID, budget_planned[0], "-100.50")
        self.assertBudgetTotals(BUDGET_PONY_ID, budget_planned[1], "0")

    @parameterized.expand(
        [
            ("every field", None, {"sequence": 10}),
            ("the fields asked", ["sequence", "position"], {"sequence": 10}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, expected)

    @parameterized.expand(
        [
            ("no rule", [], BUDGET_PONY_ID, POSITION_ALE_ID, None),
            ("own lines, own budget", OWN, BUDGET_BAGEND_ID, POSITION_BREAKFAST_ID, None),
            # The budget and the position resolve, no rule narrowing them; the line
            # written is then out of the scope of its own rule.
            ("own lines, another user's budget", OWN, BUDGET_PONY_ID, POSITION_ALE_ID, PermissionDenied),
            # With the rule of the budgets too, that budget reads as unknown.
            ("own budgets and lines, another user's budget", OWN + ["budget_manage_own"], BUDGET_PONY_ID, POSITION_ALE_ID, "budget"),
            ("own positions and lines, another user's position", OWN + ["budget_position_manage_own"], BUDGET_PONY_ID, POSITION_ALE_ID, "position"),
            ("all lines", ALL, BUDGET_PONY_ID, POSITION_ALE_ID, None),
            ("anonymous: no role, no rule", None, BUDGET_PONY_ID, POSITION_ALE_ID, None),
        ]
    )
    def test_create_access_rules(self, label, rules, budget_id, position_id, error):
        service = self.service_with_rules(rules)
        data = BudgetLineCreateSchema(**{**self.payload_create, "budget": budget_id, "position": position_id})

        if error is None:
            async_to_sync(service.create)([data])
        elif error is PermissionDenied:
            with self.assertRaises(PermissionDenied):
                async_to_sync(service.create)([data])
        else:
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(service.create)([data])
            self.assertEqual(list(ctx.exception.dict()[0]), [error])

        self.assertEqual(BudgetLine.objects.filter(name="Mushrooms").exists(), error is None)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ALL_LINE_IDS),
            ("of a budget", {"budget": BUDGET_BAGEND_ID}, [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID]),
            ("of a position", {"position": POSITION_ALE_ID}, [LINE_ALE_ID]),
            ("by amount", {"planned_amount__lt": -500}, [LINE_BREAKFAST_ID]),
            ("nothing matches", {"name": "Lembas"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [line.pk for line in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by sequence", ["sequence"], [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID, LINE_ALE_ID]),
            ("by amount, descending", ["-planned_amount"], [LINE_ALE_ID, LINE_PIPEWEED_ID, LINE_BREAKFAST_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [line.pk for line in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "name", "planned_amount"], 2, []),
            # The position is prefetched, with the fields asked on it.
            ("the position", ["id", "position__name"], 3, ["position"]),
        ]
    )
    def test_read_fields(self, label, fields, query_count, relations):
        with self.assertNumQueries(query_count):
            lines = list(async_to_sync(self.service.read)({"id": LINE_ALE_ID}, fields=fields))
            names = [getattr(lines[0], relation).name for relation in relations]

        self.assertEqual(names, ["Ale"] if relations else [])
        self.assertIn("sequence", lines[0].get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], None, ALL_LINE_IDS),
            ("own lines", OWN, None, [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID]),
            ("all lines", ALL, None, ALL_LINE_IDS),
            ("both, combined with AND", OWN + ALL, None, [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID]),
            ("two roles, combined with OR", OWN, ALL, ALL_LINE_IDS),
            ("a rule of the budgets", ["budget_manage_own"], None, ALL_LINE_IDS),
            ("anonymous: no role, no rule", None, None, ALL_LINE_IDS),
        ]
    )
    def test_read_access_rules(self, label, rules, second_role_rules, expected_pks):
        service = self.service_with_rules(rules, second_role_rules)

        pks = [line.pk for line in async_to_sync(service.read)()]

        self.assertCountEqual(pks, expected_pks)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            # A label costs no refresh of the totals.
            ("the amount", {"planned_amount": "-1200"}, 9, {"planned_amount": Decimal("-1200.00")}, ("-1200.00", "-300.00"), "-1500.00"),
            # The budget follows the position, within the same budget.
            ("to the other position", {"position": POSITION_PIPEWEED_ID}, 11, {"position_id": POSITION_PIPEWEED_ID}, ("0", "-1300.00"), "-1300.00"),
            ("the label only", {"name": "Breakfast"}, 5, {"name": "Breakfast"}, ("-1000.00", "-300.00"), "-1300.00"),
        ]
    )
    def test_update(self, label, payload, query_count, expected_values, position_planned, budget_planned):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": LINE_BREAKFAST_ID}, BudgetLineUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([line.pk for line in queryset], [LINE_BREAKFAST_ID])
        line = BudgetLine.objects.get(pk=LINE_BREAKFAST_ID)
        self.assertEqual(line.budget_id, BUDGET_BAGEND_ID)
        self.assertEqual({name: getattr(line, name) for name in expected_values}, expected_values)
        self.assertPositionTotals(POSITION_BREAKFAST_ID, position_planned[0], "-80.00")
        self.assertPositionTotals(POSITION_PIPEWEED_ID, position_planned[1], "-20.50")
        self.assertBudgetTotals(BUDGET_BAGEND_ID, budget_planned, "-100.50")

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": LINE_ALE_ID}, BudgetLineUpdateSchema(sequence=4))

        line = BudgetLine.objects.get(pk=LINE_ALE_ID)
        self.assertEqual(
            (line.name, line.sequence, line.planned_amount, line.position_id),
            ("Ale", 4, Decimal("-60.00"), POSITION_ALE_ID),
        )

    @parameterized.expand(
        [
            # `validate_data` during an update: keyed by the pk of the record.
            ("a position of another budget", BudgetLineUpdateSchema(position=POSITION_ALE_ID), 6, {LINE_BREAKFAST_ID: ["position"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown position", BudgetLineUpdateSchema(position=POSITION_UNKNOWN_ID), 2, {0: ["position"]}),
            # Built unvalidated, as another caller than the API could. Refused by
            # the null check of the service, rather than by the database.
            ("position set to null", BudgetLineUpdateSchema.model_construct(position=None), 0, {0: ["position"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": LINE_BREAKFAST_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        line = BudgetLine.objects.get(pk=LINE_BREAKFAST_ID)
        self.assertEqual((line.position_id, line.budget_id), (POSITION_BREAKFAST_ID, BUDGET_BAGEND_ID))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": LINE_BREAKFAST_ID}, {"sequence": 4})

        self.assertEqual(BudgetLine.objects.get(pk=LINE_BREAKFAST_ID).sequence, 1)

    def test_update_batch(self):
        with self.assertNumQueries(9):
            count, queryset = async_to_sync(self.service.update)({"budget": BUDGET_BAGEND_ID}, BudgetLineUpdateSchema(planned_amount="-10"))

        self.assertEqual(count, 2)
        self.assertCountEqual([line.pk for line in queryset], [LINE_BREAKFAST_ID, LINE_PIPEWEED_ID])
        self.assertBudgetTotals(BUDGET_BAGEND_ID, "-20.00", "-100.50")
        self.assertBudgetTotals(BUDGET_PONY_ID, "-60.00", "0")

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": LINE_UNKNOWN_ID}, BudgetLineUpdateSchema(name="Lembas"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(BudgetLine.objects.filter(name="Lembas").exists())

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            ("own lines, another user's", OWN, None, False),
            ("all lines", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_update_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count, queryset = async_to_sync(service.update)({"id": LINE_ALE_ID}, BudgetLineUpdateSchema(planned_amount="-1"))

        self.assertEqual(count, int(reached))
        self.assertEqual(BudgetLine.objects.get(pk=LINE_ALE_ID).planned_amount == Decimal("-1"), reached)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a line", {"id": LINE_BREAKFAST_ID}, 9, [LINE_PIPEWEED_ID, LINE_ALE_ID], ("0", "-300.00"), "-300.00"),
            ("a whole budget's", {"budget": BUDGET_BAGEND_ID}, 9, [LINE_ALE_ID], ("0", "0"), "0"),
            ("nothing matches", {"id": LINE_UNKNOWN_ID}, 5, ALL_LINE_IDS, ("-1000.00", "-300.00"), "-1300.00"),
        ]
    )
    def test_delete(self, label, filters, query_count, remaining_pks, position_planned, budget_planned):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, 3 - len(remaining_pks))
        self.assertCountEqual(BudgetLine.objects.values_list("pk", flat=True), remaining_pks)
        self.assertPositionTotals(POSITION_BREAKFAST_ID, position_planned[0], "-80.00")
        self.assertPositionTotals(POSITION_PIPEWEED_ID, position_planned[1], "-20.50")
        self.assertBudgetTotals(BUDGET_BAGEND_ID, budget_planned, "-100.50")

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            ("own lines, another user's", OWN, None, False),
            ("all lines", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_delete_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count = async_to_sync(service.delete)({"id": LINE_ALE_ID})

        self.assertEqual(count, int(reached))
        self.assertEqual(BudgetLine.objects.filter(pk=LINE_ALE_ID).exists(), not reached)

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
