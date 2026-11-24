from decimal import Decimal

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from parameterized import parameterized

from account.models import AccountCategory, AccountMovement, BudgetLine, BudgetPosition
from account.schemas import (
    AccountCategoryUpdateSchema,
    AccountMovementCreateSchema,
    AccountMovementUpdateSchema,
    BudgetPositionCreateSchema,
    BudgetPositionUpdateSchema,
)
from account.services import AccountCategoryService, AccountMovementService, BudgetPositionService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account import ACCOUNT_SHIRE_ID
from account.tests.test_services.common_account_category import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    CATEGORY_UNKNOWN_ID,
)
from account.tests.test_services.common_account_movement import LEDGER_DATE, MOVEMENT_BREAKFAST_ID
from account.tests.test_services.common_budget import BUDGET_BAGEND_ID, BUDGET_PONY_ID, BUDGET_UNKNOWN_ID
from account.tests.test_services.common_budget_line import BudgetLineServiceCommonMixin
from account.tests.test_services.common_budget_position import (
    POSITION_ALE_ID,
    POSITION_BREAKFAST_ID,
    POSITION_PIPEWEED_ID,
    POSITION_UNKNOWN_ID,
)

ALL_POSITION_IDS = [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID, POSITION_ALE_ID]

CATEGORY_ELEVENSES_ID = "01JC0000000000000000000004"

OWN = ["budget_position_manage_own"]
ALL = ["budget_position_manage_all"]

POSITION_TAKEN = "The budget already has a position for this category."


class BudgetPositionServiceTest(BudgetLineServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `BudgetPositionService`: create, read, update, delete. A position reads its
    name and color from its category, its planned total from its lines and its
    practical total from the movements of its category on the budget's account;
    the budget totals add the positions up. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # A general category no budget has a position on yet, with a movement of
        # SHIRE: a position on it reads a practical amount at once.
        cls.category_elevenses = AccountCategory.objects.create(id=CATEGORY_ELEVENSES_ID, name="Elevenses", color=9)
        AccountMovement.objects.create(
            account=cls.account_shire, amount=Decimal("-15.00"), name="Elevenses",
            date=LEDGER_DATE, category=cls.category_elevenses,
        )

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetPositionService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            (
                "a category with movements on the account",
                BUDGET_BAGEND_ID, CATEGORY_ELEVENSES_ID, 3,
                ("Elevenses", 9, 3, Decimal("0"), Decimal("-15.00")),
                ("-1300.00", "-115.50"),
            ),
            # A general category reads the movements of the budget's account only.
            (
                "a general category used by another account",
                BUDGET_PONY_ID, CATEGORY_GENERAL_ID, None,
                ("Second Breakfast", 0, 10, Decimal("0"), Decimal("0")),
                ("-60.00", "0"),
            ),
        ]
    )
    def test_create(self, label, budget_id, category_id, sequence, expected_values, budget_totals):
        data = BudgetPositionCreateSchema(budget=budget_id, category=category_id, **({"sequence": sequence} if sequence else {}))

        # The roles, the budget and the category, the insert, then the refresh
        # of the computed fields of the position and of its budget.
        with self.assertNumQueries(15):
            instances = async_to_sync(self.service.create)([data])

        self.assertEqual(len(instances), 1)
        position = BudgetPosition.objects.get(pk=instances[0].pk)
        self.assertEqual((position.budget_id, position.category_id), (budget_id, category_id))
        self.assertEqual(
            (position.name, position.color, position.sequence, position.total_planned, position.total_practical),
            expected_values,
        )
        self.assertBudgetTotals(budget_id, *budget_totals)

    @parameterized.expand(
        [
            # `validate_data`: keyed by the index of the payload.
            ("another account's category", BUDGET_PONY_ID, CATEGORY_SHIRE_ID, 6, {0: ["category"]}),
            # A database constraint: keyed on nobody.
            ("category taken", BUDGET_BAGEND_ID, CATEGORY_GENERAL_ID, 7, {"__all__": ["__all__"]}),
        ]
    )
    def test_create_invalid(self, label, budget_id, category_id, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([BudgetPositionCreateSchema(budget=budget_id, category=category_id)])

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        if "__all__" in errors:
            self.assertEqual(ctx.exception.dict()["__all__"]["__all__"], [POSITION_TAKEN])
        self.assertEqual(BudgetPosition.objects.count(), 3)
        self.assertBudgetTotals(BUDGET_BAGEND_ID, "-1300.00", "-100.50")

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"budget": BUDGET_PONY_ID, "category": CATEGORY_ELEVENSES_ID}])

        self.assertEqual(BudgetPosition.objects.count(), 3)

    @parameterized.expand(
        [
            ("unknown budget", BUDGET_UNKNOWN_ID, CATEGORY_ELEVENSES_ID, "budget"),
            ("unknown category", BUDGET_PONY_ID, CATEGORY_UNKNOWN_ID, "category"),
        ]
    )
    def test_create_relations(self, label, budget_id, category_id, error_key):
        # The roles, then the two relations, before the transaction.
        with self.assertNumQueries(3):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([BudgetPositionCreateSchema(budget=budget_id, category=category_id)])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(BudgetPosition.objects.count(), 3)

    @parameterized.expand(
        [
            ("every input valid", [(BUDGET_BAGEND_ID, CATEGORY_ELEVENSES_ID), (BUDGET_PONY_ID, CATEGORY_GENERAL_ID)], 15, None),
            ("the second input invalid", [(BUDGET_BAGEND_ID, CATEGORY_ELEVENSES_ID), (BUDGET_PONY_ID, CATEGORY_SHIRE_ID)], 6, {1: ["category"]}),
        ]
    )
    def test_create_batch(self, label, pairs, query_count, errors):
        data = [BudgetPositionCreateSchema(budget=budget, category=category) for budget, category in pairs]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual(len(instances), 2)
            self.assertEqual(BudgetPosition.objects.count(), 5)
            self.assertBudgetTotals(BUDGET_BAGEND_ID, "-1300.00", "-115.50")
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertEqual(BudgetPosition.objects.count(), 3)

    @parameterized.expand(
        [
            ("every field", None, {"sequence": 10}),
            ("the fields asked", ["sequence", "budget"], {"sequence": 10}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, expected)

    @parameterized.expand(
        [
            ("no rule", [], BUDGET_PONY_ID, None),
            ("own positions, own budget", OWN, BUDGET_BAGEND_ID, None),
            # The budget resolves, no rule of the budgets narrowing it; the
            # position written is then out of the scope of its own rule.
            ("own positions, another user's budget", OWN, BUDGET_PONY_ID, PermissionDenied),
            # With the rule of the budgets too, that budget reads as unknown.
            ("own budgets and positions, another user's budget", OWN + ["budget_manage_own"], BUDGET_PONY_ID, ServiceValidationMultiError),
            ("all positions", ALL, BUDGET_PONY_ID, None),
            ("anonymous: no role, no rule", None, BUDGET_PONY_ID, None),
        ]
    )
    def test_create_access_rules(self, label, rules, budget_id, error):
        service = self.service_with_rules(rules)
        data = BudgetPositionCreateSchema(budget=budget_id, category=CATEGORY_ELEVENSES_ID)

        if error is None:
            async_to_sync(service.create)([data])
        else:
            with self.assertRaises(error) as ctx:
                async_to_sync(service.create)([data])
            if error is ServiceValidationMultiError:
                self.assertEqual(list(ctx.exception.dict()[0]), ["budget"])

        self.assertEqual(
            BudgetPosition.objects.filter(budget_id=budget_id, category_id=CATEGORY_ELEVENSES_ID).exists(), error is None
        )

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ALL_POSITION_IDS),
            ("of a budget", {"budget": BUDGET_BAGEND_ID}, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            ("of a category", {"category": CATEGORY_BREE_ID}, [POSITION_ALE_ID]),
            ("by a stored total", {"total_practical__lt": 0}, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            ("nothing matches", {"category": CATEGORY_ELEVENSES_ID}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [position.pk for position in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by sequence", ["sequence", "name"], [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID, POSITION_ALE_ID]),
            ("by a stored name", ["name"], [POSITION_ALE_ID, POSITION_PIPEWEED_ID, POSITION_BREAKFAST_ID]),
            ("by a stored total", ["total_planned"], [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID, POSITION_ALE_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [position.pk for position in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            # Computed and stored: columns.
            ("the stored fields", ["id", "name", "color", "total_planned", "total_practical"], 2, []),
            # Each relation asked is prefetched with the fields asked on it.
            ("the relations", ["id", "budget__name", "category__name"], 4, ["budget", "category"]),
        ]
    )
    def test_read_fields(self, label, fields, query_count, relations):
        with self.assertNumQueries(query_count):
            positions = list(async_to_sync(self.service.read)({"id": POSITION_PIPEWEED_ID}, fields=fields))
            loaded = {name: getattr(positions[0], name).pk for name in relations}

        self.assertEqual(loaded, {name: pk for name, pk in [("budget", BUDGET_BAGEND_ID), ("category", CATEGORY_SHIRE_ID)] if name in relations})
        if not relations:
            position = positions[0]
            self.assertEqual(
                (position.name, position.color, position.total_planned, position.total_practical),
                ("Pipe-weed", 3, Decimal("-300.00"), Decimal("-20.50")),
            )
        self.assertIn("sequence", positions[0].get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], None, ALL_POSITION_IDS),
            ("own positions", OWN, None, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            ("all positions", ALL, None, ALL_POSITION_IDS),
            ("both, combined with AND", OWN + ALL, None, [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID]),
            ("two roles, combined with OR", OWN, ALL, ALL_POSITION_IDS),
            # A rule of the budgets holds nothing back on the positions.
            ("a rule of the budgets", ["budget_manage_own"], None, ALL_POSITION_IDS),
            ("anonymous: no role, no rule", None, None, ALL_POSITION_IDS),
        ]
    )
    def test_read_access_rules(self, label, rules, second_role_rules, expected_pks):
        service = self.service_with_rules(rules, second_role_rules)

        pks = [position.pk for position in async_to_sync(service.read)()]

        self.assertCountEqual(pks, expected_pks)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the sequence", {"sequence": 99}, 5, ("Second Breakfast", 0, 99, "-80.00"), ("-1300.00", "-100.50")),
            # Name, color and practical amount follow the category; the lines stay.
            (
                "the category",
                {"category": CATEGORY_ELEVENSES_ID},
                13,
                ("Elevenses", 9, 1, "-15.00"),
                ("-1300.00", "-35.50"),
            ),
        ]
    )
    def test_update(self, label, payload, query_count, expected_values, budget_totals):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": POSITION_BREAKFAST_ID}, BudgetPositionUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([position.pk for position in queryset], [POSITION_BREAKFAST_ID])
        position = BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID)
        self.assertEqual(
            (position.name, position.color, position.sequence, position.total_practical),
            (*expected_values[:3], Decimal(expected_values[3])),
        )
        self.assertPositionTotals(POSITION_BREAKFAST_ID, "-1000.00", expected_values[3])
        self.assertBudgetTotals(BUDGET_BAGEND_ID, *budget_totals)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": POSITION_ALE_ID}, BudgetPositionUpdateSchema(sequence=3))

        position = BudgetPosition.objects.get(pk=POSITION_ALE_ID)
        self.assertEqual((position.sequence, position.category_id, position.budget_id), (3, CATEGORY_BREE_ID, BUDGET_PONY_ID))

    def test_update_through_the_category(self):
        # Renamed through its own service, the category goes stale the name of
        # the positions reading it, refreshed in the same write.
        async_to_sync(self.get_service(AccountCategoryService, user=self.user_frodon).update)(
            {"id": CATEGORY_GENERAL_ID}, AccountCategoryUpdateSchema(name="Breakfast", color=4)
        )

        position = BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID)
        self.assertEqual((position.name, position.color), ("Breakfast", 4))

    @parameterized.expand(
        [
            # `validate_data` during an update: keyed by the pk of the record.
            ("another account's category", {"category": CATEGORY_BREE_ID}, 7, {POSITION_BREAKFAST_ID: ["category"]}),
            # A database constraint: keyed on nobody.
            ("category taken in the budget", {"category": CATEGORY_SHIRE_ID}, 8, {"__all__": ["__all__"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown category", {"category": CATEGORY_UNKNOWN_ID}, 2, {0: ["category"]}),
        ]
    )
    def test_update_invalid(self, label, payload, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": POSITION_BREAKFAST_ID}, BudgetPositionUpdateSchema(**payload))

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID).category_id, CATEGORY_GENERAL_ID)
        self.assertPositionTotals(POSITION_BREAKFAST_ID, "-1000.00", "-80.00")

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": POSITION_BREAKFAST_ID}, {"sequence": 5})

        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_BREAKFAST_ID).sequence, 1)

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"budget": BUDGET_BAGEND_ID}, BudgetPositionUpdateSchema(sequence=7))

        self.assertEqual(count, 2)
        self.assertCountEqual([position.pk for position in queryset], [POSITION_BREAKFAST_ID, POSITION_PIPEWEED_ID])
        self.assertEqual(
            dict(BudgetPosition.objects.values_list("pk", "sequence")),
            {POSITION_BREAKFAST_ID: 7, POSITION_PIPEWEED_ID: 7, POSITION_ALE_ID: 10},
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": POSITION_UNKNOWN_ID}, BudgetPositionUpdateSchema(sequence=7))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(BudgetPosition.objects.filter(sequence=7).exists())

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            ("own positions, another user's", OWN, None, False),
            ("all positions", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_update_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count, queryset = async_to_sync(service.update)({"id": POSITION_ALE_ID}, BudgetPositionUpdateSchema(sequence=1))

        self.assertEqual(count, int(reached))
        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_ALE_ID).sequence == 1, reached)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # The lines cascade, and the budget totals lose the position.
            ("a position", {"id": POSITION_BREAKFAST_ID}, 14, [POSITION_PIPEWEED_ID, POSITION_ALE_ID], ("-300.00", "-20.50")),
            ("a whole budget's", {"budget": BUDGET_BAGEND_ID}, 14, [POSITION_ALE_ID], ("0", "0")),
            ("nothing matches", {"id": POSITION_UNKNOWN_ID}, 5, ALL_POSITION_IDS, ("-1300.00", "-100.50")),
        ]
    )
    def test_delete(self, label, filters, query_count, remaining_pks, budget_totals):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, 3 - len(remaining_pks))
        self.assertCountEqual(BudgetPosition.objects.values_list("pk", flat=True), remaining_pks)
        self.assertCountEqual(BudgetLine.objects.values_list("position_id", flat=True), remaining_pks)
        self.assertBudgetTotals(BUDGET_BAGEND_ID, *budget_totals)

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            ("own positions, another user's", OWN, None, False),
            ("all positions", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_delete_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count = async_to_sync(service.delete)({"id": POSITION_ALE_ID})

        self.assertEqual(count, int(reached))
        self.assertEqual(BudgetPosition.objects.filter(pk=POSITION_ALE_ID).exists(), not reached)

    # ------------------------------------------
    # Practical Amounts
    # ------------------------------------------

    # Written through the movements, refreshed on the positions reading them.

    @parameterized.expand(
        [
            # The positions of the category, then their budgets, are refreshed with
            # the totals of the account: an uncategorized movement reaches none.
            ("in a budgeted category", {"category": CATEGORY_GENERAL_ID}, 18, "-130.00", "-20.50", "-150.50"),
            ("in the other budgeted one", {"category": CATEGORY_SHIRE_ID}, 18, "-80.00", "-70.50", "-150.50"),
            ("uncategorized", {}, 11, "-80.00", "-20.50", "-100.50"),
        ]
    )
    def test_practical_amount_movement_created(self, label, values, query_count, breakfast, pipeweed, budget):
        data = AccountMovementCreateSchema(account=ACCOUNT_SHIRE_ID, amount="-50", name="Spent", date="2026-10-01", **values)

        service = self.get_service(AccountMovementService, user=self.user_frodon)

        with self.assertNumQueries(query_count):
            async_to_sync(service.create)([data])

        self.assertPositionTotals(POSITION_BREAKFAST_ID, "-1000.00", breakfast)
        self.assertPositionTotals(POSITION_PIPEWEED_ID, "-300.00", pipeweed)
        self.assertBudgetTotals(BUDGET_BAGEND_ID, "-1300.00", budget)

    @parameterized.expand(
        [
            ("the amount", {"amount": "-100"}, 17, "-100.00", "-20.50"),
            ("recategorized", {"category": CATEGORY_SHIRE_ID}, 14, "0", "-100.50"),
            ("uncategorized", {"category": None}, 13, "0", "-20.50"),
        ]
    )
    def test_practical_amount_movement_updated(self, label, payload, query_count, breakfast, pipeweed):
        service = self.get_service(AccountMovementService, user=self.user_frodon)

        with self.assertNumQueries(query_count):
            async_to_sync(service.update)({"id": MOVEMENT_BREAKFAST_ID}, AccountMovementUpdateSchema(**payload))

        self.assertPositionTotals(POSITION_BREAKFAST_ID, "-1000.00", breakfast)
        self.assertPositionTotals(POSITION_PIPEWEED_ID, "-300.00", pipeweed)

    def test_practical_amount_movement_deleted(self):
        service = self.get_service(AccountMovementService, user=self.user_frodon)

        with self.assertNumQueries(17):
            async_to_sync(service.delete)({"id": MOVEMENT_BREAKFAST_ID})

        self.assertPositionTotals(POSITION_BREAKFAST_ID, "-1000.00", "0")
        self.assertBudgetTotals(BUDGET_BAGEND_ID, "-1300.00", "-20.50")

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
