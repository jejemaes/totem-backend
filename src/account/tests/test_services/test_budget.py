from unittest.mock import patch
from uuid import UUID

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from parameterized import parameterized

from account.models import Budget, BudgetLine, BudgetPosition
from account.schemas import BudgetCreateSchema, BudgetUpdateSchema
from account.services import BudgetService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from user.tests.test_services.common_user import USER_FRODON_ID, USER_GOLLUM_ID, USER_SAM_ID

from account.tests.test_services.common_account import ACCOUNT_BREE_ID, ACCOUNT_SHIRE_ID, ACCOUNT_UNKNOWN_ID
from account.tests.test_services.common_budget import BUDGET_BAGEND_ID, BUDGET_PONY_ID, BUDGET_UNKNOWN_ID
from account.tests.test_services.common_budget_line import BudgetLineServiceCommonMixin

ALL_BUDGET_IDS = [BUDGET_BAGEND_ID, BUDGET_PONY_ID]

USER_UNKNOWN_ID = "5263de93-e694-41ef-b873-34610551afcd"

OWN = ["budget_manage_own"]
ALL = ["budget_manage_all"]


class BudgetServiceTest(BudgetLineServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `BudgetService`: create, read, update, delete and default values. The
    totals are read from the positions, refreshed by their own writes: here they
    are only checked to survive a write of the budget. """

    payload_create = {"name": "Bag End 2027", "account": ACCOUNT_SHIRE_ID}

    def setUp(self):
        super().setUp()
        self.service = self.get_service(BudgetService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The user left out defaults to the acting user, resolved as any
            # relation: the roles, the account, the user, the insert, then the
            # refresh of the totals, and the access rules checked on the rows.
            ("the user left out: the acting user", {}, 13, {"user_id": UUID(USER_FRODON_ID), "active": True, "note": None}),
            ("the user given", {"user": USER_SAM_ID}, 13, {"user_id": UUID(USER_SAM_ID)}),
            # Given, even as null, a field is never overwritten by its default.
            ("the user explicitly null", {"user": None}, 12, {"user_id": None}),
            ("every field", {"active": False, "note": "<p>Draft</p>"}, 13, {"active": False, "note": "<p>Draft</p>"}),
        ]
    )
    def test_create(self, label, values, query_count, expected_values):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([BudgetCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual([budget.name for budget in instances], ["Bag End 2027"])
        budget = Budget.objects.get(pk=instances[0].pk)
        self.assertEqual(budget.account_id, ACCOUNT_SHIRE_ID)
        self.assertEqual({name: getattr(budget, name) for name in expected_values}, expected_values)
        # Refreshed with the creation: zero, never null.
        self.assertBudgetTotals(budget.pk, "0", "0")

    def test_create_without_acting_user(self):
        # An API key acts as nobody: there is nothing to default the user to.
        service = self.get_service(BudgetService)

        with self.assertNumQueries(11):
            instances = async_to_sync(service.create)([BudgetCreateSchema(**self.payload_create)])

        self.assertIsNone(Budget.objects.get(pk=instances[0].pk).user_id)

    # No `test_create_invalid`: the budget has no constraint, and no rule beyond
    # its relations and its access rules, tested below.

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([self.payload_create])

        self.assertEqual(Budget.objects.count(), 2)

    @parameterized.expand(
        [
            ("unknown account", {"account": ACCOUNT_UNKNOWN_ID}, 3, "account"),
            ("unknown user", {"user": USER_UNKNOWN_ID}, 3, "user"),
        ]
    )
    def test_create_relations(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([BudgetCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Budget.objects.count(), 2)

    @parameterized.expand(
        [
            ("every input valid", [{}, {"account": ACCOUNT_BREE_ID, "name": "Prancing Pony 2027"}], 13, None),
            ("the second input invalid", [{}, {"account": ACCOUNT_UNKNOWN_ID}], 3, {1: ["account"]}),
        ]
    )
    def test_create_batch(self, label, values_list, query_count, errors):
        data = [BudgetCreateSchema(**{**self.payload_create, **values}) for values in values_list]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual([budget.name for budget in instances], ["Bag End 2027", "Prancing Pony 2027"])
            self.assertEqual(Budget.objects.filter(user_id=USER_FRODON_ID).count(), 3)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertEqual(Budget.objects.count(), 2)

    @parameterized.expand(
        [
            ("bare names: pks", ["user", "active"], {"user": USER_FRODON_ID, "active": True}),
            ("every field: pks", None, {"user": USER_FRODON_ID, "active": True, "note": None}),
            ("a sub-lookup on no relation is ignored", ["active__id"], {"active": True}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        # The pk of the acting user, whatever its python type.
        self.assertEqual({name: str(value) if name == "user" else value for name, value in values.items()}, expected)

    def test_default_values_of_a_relation(self):
        # The roles of the acting user, then the user, loaded with the fields asked.
        with self.assertNumQueries(2):
            values = async_to_sync(self.service.default_values)(["user__id", "user__username"])

        user = values["user"]
        self.assertEqual((user.pk, user.username), (UUID(USER_FRODON_ID), "frodon@lacomte.com"))
        self.assertIn("email", user.get_deferred_fields())

    def test_default_values_without_acting_user(self):
        service = self.get_service(BudgetService)

        with self.assertNumQueries(0):
            values = async_to_sync(service.default_values)(["user", "active"])

        self.assertEqual((values.get("user"), values["active"]), (None, True))

    @parameterized.expand(
        [
            ("the acting user", USER_FRODON_ID, True),
            ("out of reach: dropped", USER_GOLLUM_ID, False),
        ]
    )
    def test_default_values_access_rules(self, label, user_id, kept):
        # A default the acting user may not read is dropped rather than rendered:
        # the creation would refuse it. The rule is the one of the users.
        self.role.rules = ["user_manage_own_profile"]
        self.role.save()
        service = self.get_service(BudgetService, user=self.user_frodon)

        async def propose(service, fields=None):
            return {"user": UUID(user_id)}

        with patch.object(BudgetService, "_default_values", propose):
            values = async_to_sync(service.default_values)(["user__id"])

        self.assertEqual({name: value.pk for name, value in values.items()}, {"user": UUID(user_id)} if kept else {})

    def test_create_reads_the_defaults_in_pks(self):
        # From `_default_values`: what `default_values` adds -- records -- is no
        # value a creation can write.
        with patch.object(BudgetService, "default_values", side_effect=AssertionError("records, not pks")):
            instances = async_to_sync(self.service.create)([BudgetCreateSchema(**self.payload_create)])

        self.assertEqual(Budget.objects.get(pk=instances[0].pk).user_id, UUID(USER_FRODON_ID))

    @parameterized.expand(
        [
            ("no rule", [], None, {}, True),
            ("own budgets, in charge", OWN, None, {}, True),
            # The default user makes it one's own: no need to name oneself.
            ("own budgets, for another user", OWN, None, {"user": USER_GOLLUM_ID}, False),
            ("own budgets, for nobody", OWN, None, {"user": None}, False),
            ("all budgets, for another user", ALL, None, {"user": USER_GOLLUM_ID}, True),
            ("both, combined with AND", OWN + ALL, None, {"user": USER_GOLLUM_ID}, False),
            ("two roles, combined with OR", OWN, ALL, {"user": USER_GOLLUM_ID}, True),
            ("anonymous: no role, no rule", None, None, {"user": USER_GOLLUM_ID}, True),
        ]
    )
    def test_create_access_rules(self, label, rules, second_role_rules, values, created):
        service = self.service_with_rules(rules, second_role_rules)
        data = BudgetCreateSchema(**{**self.payload_create, **values})

        if created:
            instances = async_to_sync(service.create)([data])
            self.assertEqual([budget.name for budget in instances], ["Bag End 2027"])
        else:
            # Checked on the rows written, inside the transaction: rolled back.
            with self.assertRaises(PermissionDenied):
                async_to_sync(service.create)([data])

        self.assertEqual(Budget.objects.filter(name="Bag End 2027").exists(), created)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ALL_BUDGET_IDS),
            ("of an account", {"account": ACCOUNT_SHIRE_ID}, [BUDGET_BAGEND_ID]),
            ("of a user", {"user": USER_GOLLUM_ID}, [BUDGET_PONY_ID]),
            ("by a stored total", {"total_planned_amount__lt": -100}, [BUDGET_BAGEND_ID]),
            ("nothing matches", {"active": False}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [budget.pk for budget in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by name", ["name"], [BUDGET_BAGEND_ID, BUDGET_PONY_ID]),
            ("by a stored total", ["total_planned_amount"], [BUDGET_BAGEND_ID, BUDGET_PONY_ID]),
            ("by name, descending", ["-name"], [BUDGET_PONY_ID, BUDGET_BAGEND_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [budget.pk for budget in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            # Stored totals are columns.
            ("the stored totals", ["id", "total_planned_amount", "total_practical_amount"], 2, {"total_planned_amount": "-1300.00"}),
            # A virtual field: the budgets, then its own reads. The sale has no category.
            ("a virtual field", ["id", "uncategorized_movement_count"], 5, {"uncategorized_movement_count": 1}),
        ]
    )
    def test_read_fields(self, label, fields, query_count, expected_values):
        with self.assertNumQueries(query_count):
            budgets = list(async_to_sync(self.service.read)({"id": BUDGET_BAGEND_ID}, fields=fields))

        self.assertEqual(
            {name: str(getattr(budgets[0], name)) if isinstance(value, str) else getattr(budgets[0], name) for name, value in expected_values.items()},
            expected_values,
        )
        self.assertIn("note", budgets[0].get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], None, ALL_BUDGET_IDS),
            ("own budgets", OWN, None, [BUDGET_BAGEND_ID]),
            ("all budgets", ALL, None, ALL_BUDGET_IDS),
            ("both, combined with AND", OWN + ALL, None, [BUDGET_BAGEND_ID]),
            ("two roles, combined with OR", OWN, ALL, ALL_BUDGET_IDS),
            # A rule of another model holds nothing back here.
            ("a rule of the positions", ["budget_position_manage_own"], None, ALL_BUDGET_IDS),
            ("anonymous: no role, no rule", None, None, ALL_BUDGET_IDS),
        ]
    )
    def test_read_access_rules(self, label, rules, second_role_rules, expected_pks):
        service = self.service_with_rules(rules, second_role_rules)

        pks = [budget.pk for budget in async_to_sync(service.read)()]

        self.assertCountEqual(pks, expected_pks)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the name", {"name": "Bag End 2026 (revised)"}, 5, {"name": "Bag End 2026 (revised)"}),
            ("state and note", {"active": False, "note": "<p>Closed</p>"}, 5, {"active": False, "note": "<p>Closed</p>"}),
            ("handed over", {"user": USER_SAM_ID}, 6, {"user_id": UUID(USER_SAM_ID)}),
            ("in charge of nobody", {"user": None}, 5, {"user_id": None}),
        ]
    )
    def test_update(self, label, payload, query_count, expected_values):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": BUDGET_BAGEND_ID}, BudgetUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([budget.pk for budget in queryset], [BUDGET_BAGEND_ID])
        budget = Budget.objects.get(pk=BUDGET_BAGEND_ID)
        self.assertEqual({name: getattr(budget, name) for name in expected_values}, expected_values)
        self.assertBudgetTotals(BUDGET_BAGEND_ID, "-1300.00", "-100.50")

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": BUDGET_PONY_ID}, BudgetUpdateSchema(note="<p>Butterbur</p>"))

        budget = Budget.objects.get(pk=BUDGET_PONY_ID)
        self.assertEqual(
            (budget.name, budget.user_id, budget.active, budget.note),
            ("Prancing Pony 2026", UUID(USER_GOLLUM_ID), True, "<p>Butterbur</p>"),
        )

    @parameterized.expand(
        [
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown user", BudgetUpdateSchema(user=USER_UNKNOWN_ID), 2, {0: ["user"]}),
            # Built unvalidated, as another caller than the API could.
            ("name set to null", BudgetUpdateSchema.model_construct(name=None), 0, {0: ["name"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": BUDGET_BAGEND_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        budget = Budget.objects.get(pk=BUDGET_BAGEND_ID)
        self.assertEqual((budget.name, budget.user_id), ("Bag End 2026", UUID(USER_FRODON_ID)))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": BUDGET_BAGEND_ID}, {"name": "Bag End"})

        self.assertEqual(Budget.objects.get(pk=BUDGET_BAGEND_ID).name, "Bag End 2026")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"active": True}, BudgetUpdateSchema(active=False))

        self.assertEqual(count, 2)
        self.assertCountEqual([budget.pk for budget in queryset], ALL_BUDGET_IDS)
        self.assertFalse(Budget.objects.filter(active=True).exists())

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": BUDGET_UNKNOWN_ID}, BudgetUpdateSchema(name="Mordor"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(Budget.objects.filter(name="Mordor").exists())

    @parameterized.expand(
        [
            ("no rule", [], None, BUDGET_PONY_ID, True),
            ("own budgets, another user's", OWN, None, BUDGET_PONY_ID, False),
            # The rule is checked on the rows the update reaches, not on what it
            # writes: handing one's budget over is an update of one's own budget.
            ("own budgets, handed over", OWN, None, BUDGET_BAGEND_ID, True),
            ("all budgets", ALL, None, BUDGET_PONY_ID, True),
            ("both, combined with AND", OWN + ALL, None, BUDGET_PONY_ID, False),
            ("two roles, combined with OR", OWN, ALL, BUDGET_PONY_ID, True),
            ("anonymous: no role, no rule", None, None, BUDGET_PONY_ID, True),
        ]
    )
    def test_update_access_rules(self, label, rules, second_role_rules, pk, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count, queryset = async_to_sync(service.update)({"id": pk}, BudgetUpdateSchema(user=USER_SAM_ID))

        # Out of reach is no error: the row is not matched.
        self.assertEqual(count, int(reached))
        self.assertEqual(Budget.objects.get(pk=pk).user_id == UUID(USER_SAM_ID), reached)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # The positions and lines cascade; the other budget keeps its own.
            ("a budget", {"id": BUDGET_BAGEND_ID}, 22, 1, [BUDGET_PONY_ID]),
            ("every budget", {}, 22, 2, []),
            ("nothing matches", {"id": BUDGET_UNKNOWN_ID}, 5, 0, ALL_BUDGET_IDS),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, remaining_pks):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertCountEqual(Budget.objects.values_list("pk", flat=True), remaining_pks)
        self.assertCountEqual(BudgetPosition.objects.values_list("budget_id", flat=True).distinct(), remaining_pks)
        self.assertCountEqual(BudgetLine.objects.values_list("budget_id", flat=True).distinct(), remaining_pks)

    @parameterized.expand(
        [
            ("no rule", [], None, True),
            ("own budgets, another user's", OWN, None, False),
            ("all budgets", ALL, None, True),
            ("both, combined with AND", OWN + ALL, None, False),
            ("two roles, combined with OR", OWN, ALL, True),
            ("anonymous: no role, no rule", None, None, True),
        ]
    )
    def test_delete_access_rules(self, label, rules, second_role_rules, reached):
        service = self.service_with_rules(rules, second_role_rules)

        count = async_to_sync(service.delete)({"id": BUDGET_PONY_ID})

        self.assertEqual(count, int(reached))
        self.assertEqual(Budget.objects.filter(pk=BUDGET_PONY_ID).exists(), not reached)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def service_with_rules(self, rules, second_role_rules=None):
        """ The service acting as Frodon, whose role holds `rules`; with
        `second_role_rules`, Frodon holds a second role with those. `rules=None`
        is an anonymous caller. """
        if rules is None:
            return self.get_service(BudgetService)
        self.role.rules = rules
        self.role.save()
        if second_role_rules is not None:
            self.role_hobbit.rules = second_role_rules
            self.role_hobbit.save()
            self.user_frodon.roles.add(self.role_hobbit)
        return self.get_service(BudgetService, user=self.user_frodon)
