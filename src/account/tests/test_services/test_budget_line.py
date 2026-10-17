from decimal import Decimal

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import BudgetLine
from account.schemas import (
    AccountMovementCreateSchema,
    AccountMovementUpdateSchema,
    BudgetLineCreateSchema,
    BudgetLineUpdateSchema,
)
from account.services import AccountMovementService, BudgetLineService
from account.tests.common import (
    ACCOUNT_ID1,
    BUDGET_ID1,
    BUDGET_ID2,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    LINE_FEES_ID,
    LINE_RENT_ID,
    LINE_STOCK_ID,
    MOVEMENT_ID2,
    POSITION_FEES_ID,
    POSITION_RENT_ID,
    POSITION_STOCK_ID,
    BudgetTestMixin,
)
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError


class TestBudgetLineService(BudgetTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(BudgetLineService)

    def as_role(self, role_pk):
        self.grant(self.user, role_pk)
        return Environment(user=self.user, language="en-us").get(BudgetLineService)

    def _payload(self, **values):
        return {"budget": BUDGET_ID1, "position": POSITION_RENT_ID, "name": "Deposit", "planned_amount": "-500", **values}

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("missing name", {"budget": BUDGET_ID1, "position": POSITION_RENT_ID, "planned_amount": "1"}),
            ("missing position", {"budget": BUDGET_ID1, "name": "x", "planned_amount": "1"}),
            ("missing amount", {"budget": BUDGET_ID1, "position": POSITION_RENT_ID, "name": "x"}),
            ("too many decimals", {"budget": BUDGET_ID1, "position": POSITION_RENT_ID, "name": "x", "planned_amount": "1.001"}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                BudgetLineCreateSchema(**payload)

    def test_update_schema_has_no_budget(self):
        # Derived from the position, never written by a client.
        self.assertNotIn("budget", BudgetLineUpdateSchema.model_fields)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_valid(self):
        instances = async_to_sync(self.service.create)([BudgetLineCreateSchema(**self._payload(sequence=5))])

        line = BudgetLine.objects.get(pk=instances[0].pk)
        self.assertEqual((line.budget_id, line.sequence, line.planned_amount), (BUDGET_ID1, 5, Decimal("-500.00")))
        self.assertPositionTotals(POSITION_RENT_ID, "-1500.00", "-80.00")
        self.assertBudgetTotals(BUDGET_ID1, "-1800.00", "-100.50")

    def test_create_many_refreshes_once(self):
        data = [
            BudgetLineCreateSchema(**self._payload(planned_amount="-1")),
            BudgetLineCreateSchema(**self._payload(position=POSITION_STOCK_ID, planned_amount="-2")),
            BudgetLineCreateSchema(**self._payload(budget=BUDGET_ID2, position=POSITION_FEES_ID, planned_amount="-3")),
        ]
        async_to_sync(self.service.create)(data)

        self.assertBudgetTotals(BUDGET_ID1, "-1303.00", "-100.50")
        self.assertBudgetTotals(BUDGET_ID2, "-63.00", "0")

    @parameterized.expand(
        [
            ("position of another budget", {"position": POSITION_FEES_ID}, "position"),
            ("unknown position", {"position": "01JP0000000000000000000099"}, "position"),
            ("unknown budget", {"budget": "01JB0000000000000000000099"}, "budget"),
        ]
    )
    def test_create_invalid(self, dummy, values, error_key):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([BudgetLineCreateSchema(**self._payload(**values))])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertBudgetTotals(BUDGET_ID1, "-1300.00", "-100.50")

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"budget": BUDGET_ID1}, ["id", "name", "planned_amount"], 2, 2),
            ({"position": POSITION_FEES_ID}, ["id", "position"], 3, 1),  # prefetches the position
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields + (["position__name"] if "position" in fields else []))
            self.assertEqual(len(qs), expected_count)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("amount", {"planned_amount": "-1200"}, ("-1200.00", "-300.00"), "-1500.00"),
            ("to the other position", {"position": POSITION_STOCK_ID}, ("0", "-1300.00"), "-1300.00"),
            ("label only", {"name": "Rent (revised)"}, ("-1000.00", "-300.00"), "-1300.00"),
        ]
    )
    def test_update_valid(self, dummy, payload, position_planned, budget_planned):
        count, queryset = async_to_sync(self.service.update)({"id": LINE_RENT_ID}, BudgetLineUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual(BudgetLine.objects.get(pk=LINE_RENT_ID).budget_id, BUDGET_ID1)
        self.assertEqual(
            (BudgetLine.objects.get(pk=LINE_RENT_ID).position_id), payload.get("position", POSITION_RENT_ID)
        )
        self.assertPositionTotals(POSITION_RENT_ID, position_planned[0], "-80.00")
        self.assertPositionTotals(POSITION_STOCK_ID, position_planned[1], "-20.50")
        self.assertBudgetTotals(BUDGET_ID1, budget_planned, "-100.50")

    def test_update_to_a_position_of_another_budget(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)({"id": LINE_RENT_ID}, BudgetLineUpdateSchema(position=POSITION_FEES_ID))

        self.assertEqual(list(ctx.exception.dict()[LINE_RENT_ID]), ["position"])
        self.assertEqual(BudgetLine.objects.get(pk=LINE_RENT_ID).budget_id, BUDGET_ID1)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete(self):
        count = async_to_sync(self.service.delete)({"id": LINE_RENT_ID})

        self.assertEqual(count, 1)
        self.assertPositionTotals(POSITION_RENT_ID, "0", "-80.00")
        self.assertBudgetTotals(BUDGET_ID1, "-300.00", "-100.50")

    # ------------------------------------------
    # Tests Practical Amounts
    # ------------------------------------------

    @parameterized.expand(
        [
            ("in a budgeted category", {"category": CATEGORY_GENERAL_ID}, "-130.00", "-20.50", "-150.50"),
            ("in the other budgeted one", {"category": CATEGORY_SHOP_ID}, "-80.00", "-70.50", "-150.50"),
            ("uncategorized", {}, "-80.00", "-20.50", "-100.50"),
        ]
    )
    def test_movement_create(self, dummy, values, rent, stock, budget):
        data = AccountMovementCreateSchema(account=ACCOUNT_ID1, amount="-50", name="Spent", date="2026-10-01", **values)
        async_to_sync(self.env.get(AccountMovementService).create)([data])

        self.assertPositionTotals(POSITION_RENT_ID, "-1000.00", rent)
        self.assertPositionTotals(POSITION_STOCK_ID, "-300.00", stock)
        self.assertBudgetTotals(BUDGET_ID1, "-1300.00", budget)

    @parameterized.expand(
        [
            ("amount", {"amount": "-100"}, "-100.00", "-20.50"),
            ("recategorized", {"category": CATEGORY_SHOP_ID}, "0", "-100.50"),
            ("uncategorized", {"category": None}, "0", "-20.50"),
        ]
    )
    def test_movement_update(self, dummy, payload, rent, stock):
        async_to_sync(self.env.get(AccountMovementService).update)(
            {"id": MOVEMENT_ID2}, AccountMovementUpdateSchema(**payload)
        )

        self.assertPositionTotals(POSITION_RENT_ID, "-1000.00", rent)
        self.assertPositionTotals(POSITION_STOCK_ID, "-300.00", stock)

    def test_movement_delete(self):
        async_to_sync(self.env.get(AccountMovementService).delete)({"id": MOVEMENT_ID2})

        self.assertPositionTotals(POSITION_RENT_ID, "-1000.00", "0")
        self.assertBudgetTotals(BUDGET_ID1, "-1300.00", "-20.50")

    # ------------------------------------------
    # Tests Access Rules
    # ------------------------------------------

    @parameterized.expand(
        [
            ("BUDGET_USER", [LINE_RENT_ID, LINE_STOCK_ID]),
            ("BUDGET_READER", [LINE_RENT_ID, LINE_STOCK_ID, LINE_FEES_ID]),
            ("BUDGET_ADMINISTRATOR", [LINE_RENT_ID, LINE_STOCK_ID, LINE_FEES_ID]),
        ]
    )
    def test_read_access_rules(self, role, ids):
        qs = async_to_sync(self.as_role(role).read)()

        self.assertEqual(sorted(qs.values_list("id", flat=True)), ids)

    @parameterized.expand([("BUDGET_USER", 0), ("BUDGET_ADMINISTRATOR", 1)])
    def test_update_another_users_line(self, role, affected_row):
        count, queryset = async_to_sync(self.as_role(role).update)(
            {"id": LINE_FEES_ID}, BudgetLineUpdateSchema(planned_amount="-1")
        )
        self.assertEqual(count, affected_row)

    @parameterized.expand([("BUDGET_USER", 0), ("BUDGET_ADMINISTRATOR", 1)])
    def test_delete_another_users_line(self, role, affected_row):
        self.assertEqual(async_to_sync(self.as_role(role).delete)({"id": LINE_FEES_ID}), affected_row)

    @parameterized.expand(
        [
            # Out of scope, a budget or a position reads as unknown. One at a time:
            # with both unknown, `to_internal_values` only keeps one of the errors.
            ("another user's budget", {"budget": BUDGET_ID2, "position": POSITION_RENT_ID}, "budget"),
            ("another user's position", {"position": POSITION_FEES_ID}, "position"),
        ]
    )
    def test_user_cannot_add_to_another_users_budget(self, dummy, values, error_key):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.as_role("BUDGET_USER").create)([BudgetLineCreateSchema(**self._payload(**values))])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
