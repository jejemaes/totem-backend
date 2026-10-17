from uuid import UUID

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import Budget, BudgetLine, BudgetPosition
from account.schemas import BudgetCreateSchema, BudgetUpdateSchema
from account.services import AccountService, BudgetService
from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    BUDGET_ID1,
    BUDGET_ID2,
    USER_ID1,
    USER_ID2,
    BudgetTestMixin,
)
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError


class TestBudgetService(BudgetTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(BudgetService)

    def as_role(self, role_pk):
        # A fresh environment: it memoizes the roles of its user.
        self.grant(self.user, role_pk)
        return Environment(user=self.user, language="en-us").get(BudgetService)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("missing name", {"account": ACCOUNT_ID1}),
            ("missing account", {"name": "2027"}),
            ("user not a uuid4", {"name": "2027", "account": ACCOUNT_ID1, "user": "00000000-0000-0000-0000-000000000000"}),
            ("script in the note", {"name": "2027", "account": ACCOUNT_ID1, "note": "<script>alert(1)</script>"}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                BudgetCreateSchema(**payload)

    def test_update_schema_has_no_account(self):
        # The positions were chosen among the categories of that account.
        self.assertNotIn("account", BudgetUpdateSchema.model_fields)

    @parameterized.expand([(BudgetCreateSchema,), (BudgetUpdateSchema,)])
    def test_totals_are_not_writable(self, schema):
        self.assertFalse(
            {"total_planned_amount", "total_practical_amount", "uncategorized_movement_count"}
            & set(schema.model_fields)
        )

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("user left out: the acting user", {}, USER_ID1),
            ("user given", {"user": USER_ID2}, USER_ID2),
            ("user explicitly null", {"user": None}, None),
        ]
    )
    def test_create_user(self, dummy, values, user_id):
        data = BudgetCreateSchema(name="2027", account=ACCOUNT_ID1, **values)
        instances = async_to_sync(self.service.create)([data])

        self.assertEqual(Budget.objects.get(pk=instances[0].pk).user_id, user_id and UUID(user_id))

    def test_create_without_acting_user(self):
        # An application token acts as nobody: nothing to default to.
        service = Environment(None).get(BudgetService)
        instances = async_to_sync(service.create)([BudgetCreateSchema(name="2027", account=ACCOUNT_ID1)])

        self.assertIsNone(Budget.objects.get(pk=instances[0].pk).user_id)

    def test_create_valid(self):
        data = BudgetCreateSchema(
            name="2027", account=ACCOUNT_ID1, active=False, note="<p>Draft</p>"
        )
        instances = async_to_sync(self.service.create)([data])

        budget = Budget.objects.get(pk=instances[0].pk)
        self.assertEqual(
            (budget.name, budget.account_id, budget.active, budget.note),
            ("2027", ACCOUNT_ID1, False, "<p>Draft</p>"),
        )
        # Refreshed with the creation: zero, never null.
        self.assertBudgetTotals(budget.pk, "0", "0")

    @parameterized.expand(
        [
            ("unknown account", {"account": "01JA0000000000000000000099"}, "account"),
            ("unknown user", {"user": "5e0e8b5c-2b1f-4c1e-9a3e-1d2f3a4b5c6d"}, "user"),
        ]
    )
    def test_create_invalid(self, dummy, values, error_key):
        data = BudgetCreateSchema(**{"name": "2027", "account": ACCOUNT_ID1, **values})
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([data])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"account": ACCOUNT_ID1}, ["id", "total_planned_amount", "total_practical_amount"], 2, 1),
            ({}, ["id", "user", "account"], 2, 2),
            # A virtual field: the budgets, then its own three reads.
            ({}, ["id", "uncategorized_movement_count"], 5, 2),
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields)
            self.assertEqual(len(qs), expected_count)

    def test_read_computed(self):
        qs = async_to_sync(self.service.read)(
            {"id": BUDGET_ID1}, fields=["id", "total_planned_amount", "uncategorized_movement_count"]
        )
        self.assertBudgetTotals(BUDGET_ID1, "-1300.00", "-100.50")
        # The sale of SHOP has no category.
        self.assertEqual(qs[0].uncategorized_movement_count, 1)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"id": BUDGET_ID1}, {"name": "Shop 2026 (revised)"}, 1),
            ({"id": BUDGET_ID1}, {"active": False, "note": "<p>Closed</p>"}, 1),
            ({"id": BUDGET_ID1}, {"user": USER_ID2}, 1),
            ({"id": BUDGET_ID1}, {"user": None}, 1),
            ({"name": "Unknown"}, {"name": "Nothing"}, 0),
        ]
    )
    def test_update_valid(self, filters, payload, affected_row):
        count, queryset = async_to_sync(self.service.update)(filters, BudgetUpdateSchema(**payload))
        self.assertEqual(count, affected_row)

    def test_update_keeps_the_totals(self):
        async_to_sync(self.service.update)({"id": BUDGET_ID1}, BudgetUpdateSchema(name="Revised"))

        self.assertBudgetTotals(BUDGET_ID1, "-1300.00", "-100.50")

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete_cascades(self):
        count = async_to_sync(self.service.delete)({"id": BUDGET_ID1})

        self.assertEqual(count, 1)
        self.assertFalse(BudgetPosition.objects.filter(budget_id=BUDGET_ID1).exists())
        self.assertFalse(BudgetLine.objects.filter(budget_id=BUDGET_ID1).exists())
        self.assertTrue(BudgetLine.objects.filter(budget_id=BUDGET_ID2).exists())

    def test_account_with_budget_is_protected(self):
        # BANK has no movement, but a budget.
        service = self.env.get(AccountService)
        with self.assertRaises(ServiceValidationMultiError):
            async_to_sync(service.delete)({"id": ACCOUNT_ID2})

    # ------------------------------------------
    # Tests Access Rules
    # ------------------------------------------

    @parameterized.expand(
        [
            ("BUDGET_USER", [BUDGET_ID1]),
            ("BUDGET_READER", [BUDGET_ID1, BUDGET_ID2]),
            ("BUDGET_ADMINISTRATOR", [BUDGET_ID1, BUDGET_ID2]),
        ]
    )
    def test_read_access_rules(self, role, ids):
        service = self.as_role(role)
        qs = async_to_sync(service.read)()

        self.assertEqual(sorted(qs.values_list("id", flat=True)), ids)

    @parameterized.expand(
        [
            ("BUDGET_USER", 0),
            ("BUDGET_ADMINISTRATOR", 1),
        ]
    )
    def test_update_another_users_budget(self, role, affected_row):
        service = self.as_role(role)
        count, queryset = async_to_sync(service.update)({"id": BUDGET_ID2}, BudgetUpdateSchema(name="Mine"))

        self.assertEqual(count, affected_row)

    @parameterized.expand(
        [
            ("BUDGET_USER", 0),
            ("BUDGET_ADMINISTRATOR", 1),
        ]
    )
    def test_delete_another_users_budget(self, role, affected_row):
        service = self.as_role(role)

        self.assertEqual(async_to_sync(service.delete)({"id": BUDGET_ID2}), affected_row)

    def test_user_creates_their_own_budget(self):
        service = self.as_role("BUDGET_USER")
        instances = async_to_sync(service.create)([BudgetCreateSchema(name="2027", account=ACCOUNT_ID1)])

        self.assertEqual(Budget.objects.get(pk=instances[0].pk).user_id, UUID(USER_ID1))

    @parameterized.expand(
        [
            ("for another user", {"user": USER_ID2}),
            ("for nobody", {"user": None}),
        ]
    )
    def test_user_cannot_create_outside_their_scope(self, dummy, values):
        service = self.as_role("BUDGET_USER")
        with self.assertRaises(PermissionDenied):
            async_to_sync(service.create)([BudgetCreateSchema(name="2027", account=ACCOUNT_ID1, **values)])

        self.assertFalse(Budget.objects.filter(name="2027").exists())

    def test_user_cannot_hand_their_budget_over(self):
        # The rule is checked on the rows the update reaches, not on what it writes:
        # handing a budget over is an update of one's own budget. Pinned so a
        # change of that behaviour is noticed.
        service = self.as_role("BUDGET_USER")
        count, queryset = async_to_sync(service.update)({"id": BUDGET_ID1}, BudgetUpdateSchema(user=USER_ID2))

        self.assertEqual(count, 1)
        self.assertEqual(Budget.objects.get(pk=BUDGET_ID1).user_id, UUID(USER_ID2))
