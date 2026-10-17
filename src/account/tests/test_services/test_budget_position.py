from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import AccountCategory, BudgetLine, BudgetPosition
from account.schemas import BudgetPositionCreateSchema, BudgetPositionUpdateSchema
from account.services import BudgetPositionService
from account.tests.common import (
    BUDGET_ID1,
    BUDGET_ID2,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    POSITION_FEES_ID,
    POSITION_RENT_ID,
    POSITION_STOCK_ID,
    BudgetTestMixin,
)
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError


class TestBudgetPositionService(BudgetTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category_food = AccountCategory.objects.create(name="Food", color=9)

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(BudgetPositionService)

    def as_role(self, role_pk):
        self.grant(self.user, role_pk)
        return Environment(user=self.user, language="en-us").get(BudgetPositionService)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("missing budget", {"category": CATEGORY_GENERAL_ID}),
            ("missing category", {"budget": BUDGET_ID1}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                BudgetPositionCreateSchema(**payload)

    def test_update_schema_has_no_budget(self):
        self.assertNotIn("budget", BudgetPositionUpdateSchema.model_fields)

    @parameterized.expand([(BudgetPositionCreateSchema,), (BudgetPositionUpdateSchema,)])
    def test_computed_fields_are_not_writable(self, schema):
        self.assertFalse(
            {"name", "color", "total_planned", "total_practical"} & set(schema.model_fields)
        )

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_valid(self):
        data = BudgetPositionCreateSchema(budget=BUDGET_ID1, category=str(self.category_food.pk), sequence=3)
        instances = async_to_sync(self.service.create)([data])

        position = BudgetPosition.objects.get(pk=instances[0].pk)
        # Read from the category, refreshed with the creation.
        self.assertEqual(
            (position.name, position.color, position.sequence, position.total_planned, position.total_practical),
            ("Food", 9, 3, 0, 0),
        )

    @parameterized.expand(
        [
            ("own account's category", BUDGET_ID2, CATEGORY_GENERAL_ID),
            ("general category", BUDGET_ID2, None),
        ]
    )
    def test_create_category_applicable(self, dummy, budget_id, category_id):
        category_id = category_id or str(self.category_food.pk)
        async_to_sync(self.service.create)([BudgetPositionCreateSchema(budget=budget_id, category=category_id)])

    @parameterized.expand(
        [
            ("another account's category", {"budget": BUDGET_ID2, "category": CATEGORY_SHOP_ID}, [0, "category"]),
            ("unknown budget", {"budget": "01JB0000000000000000000099", "category": CATEGORY_GENERAL_ID}, [0, "budget"]),
            # Reported by the database, for the whole write.
            ("category taken", {"budget": BUDGET_ID1, "category": CATEGORY_GENERAL_ID}, ["__all__", "__all__"]),
        ]
    )
    def test_create_invalid(self, dummy, payload, error_path):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([BudgetPositionCreateSchema(**payload)])

        key, field = error_path
        self.assertIn(field, ctx.exception.dict()[key])

    def test_create_with_movements_reads_them(self):
        # BANK's budget gets a position on the general Rent: SHOP's rent is no part of it.
        instances = async_to_sync(self.service.create)(
            [BudgetPositionCreateSchema(budget=BUDGET_ID2, category=CATEGORY_GENERAL_ID)]
        )
        self.assertPositionTotals(instances[0].pk, "0", "0")

        # SHOP's budget, on a category of SHOP with movements: read at once.
        BudgetPosition.objects.filter(pk=POSITION_STOCK_ID).delete()
        instances = async_to_sync(self.service.create)(
            [BudgetPositionCreateSchema(budget=BUDGET_ID1, category=CATEGORY_SHOP_ID)]
        )
        self.assertPositionTotals(instances[0].pk, "0", "-20.50")
        self.assertBudgetTotals(BUDGET_ID1, "-1000.00", "-100.50")

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"budget": BUDGET_ID1}, ["id", "name", "total_planned", "total_practical"], 2, 2),
            ({"budget": BUDGET_ID2}, ["id", "category"], 2, 1),
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields)
            self.assertEqual(len(qs), expected_count)

    def test_read_totals(self):
        self.assertPositionTotals(POSITION_RENT_ID, "-1000.00", "-80.00")
        self.assertPositionTotals(POSITION_STOCK_ID, "-300.00", "-20.50")
        self.assertPositionTotals(POSITION_FEES_ID, "-60.00", "0")

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_update_category(self):
        count, queryset = async_to_sync(self.service.update)(
            {"id": POSITION_RENT_ID}, BudgetPositionUpdateSchema(category=str(self.category_food.pk))
        )

        self.assertEqual(count, 1)
        position = BudgetPosition.objects.get(pk=POSITION_RENT_ID)
        # Name, color and practical amount follow the category; the lines stay.
        self.assertEqual((position.name, position.color), ("Food", 9))
        self.assertPositionTotals(POSITION_RENT_ID, "-1000.00", "0")
        self.assertBudgetTotals(BUDGET_ID1, "-1300.00", "-20.50")

    def test_update_sequence(self):
        count, queryset = async_to_sync(self.service.update)(
            {"id": POSITION_RENT_ID}, BudgetPositionUpdateSchema(sequence=99)
        )
        self.assertEqual((count, BudgetPosition.objects.get(pk=POSITION_RENT_ID).sequence), (1, 99))

    def test_update_category_of_another_account(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": POSITION_RENT_ID}, BudgetPositionUpdateSchema(category=CATEGORY_BANK_ID)
            )

        self.assertEqual(list(ctx.exception.dict()[POSITION_RENT_ID]), ["category"])

    def test_category_renamed(self):
        AccountCategory.objects.filter(pk=CATEGORY_GENERAL_ID).update(name="Rental")  # around the service
        BudgetPosition.objects.filter(pk=POSITION_RENT_ID).refresh_computed()

        self.assertEqual(BudgetPosition.objects.get(pk=POSITION_RENT_ID).name, "Rental")

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete(self):
        count = async_to_sync(self.service.delete)({"id": POSITION_RENT_ID})

        self.assertEqual(count, 1)
        self.assertFalse(BudgetLine.objects.filter(position_id=POSITION_RENT_ID).exists())
        self.assertBudgetTotals(BUDGET_ID1, "-300.00", "-20.50")

    # ------------------------------------------
    # Tests Access Rules
    # ------------------------------------------

    @parameterized.expand(
        [
            ("BUDGET_USER", [POSITION_RENT_ID, POSITION_STOCK_ID]),
            ("BUDGET_READER", [POSITION_RENT_ID, POSITION_STOCK_ID, POSITION_FEES_ID]),
            ("BUDGET_ADMINISTRATOR", [POSITION_RENT_ID, POSITION_STOCK_ID, POSITION_FEES_ID]),
        ]
    )
    def test_read_access_rules(self, role, ids):
        qs = async_to_sync(self.as_role(role).read)()

        self.assertEqual(sorted(qs.values_list("id", flat=True)), ids)

    @parameterized.expand([("BUDGET_USER", 0), ("BUDGET_ADMINISTRATOR", 1)])
    def test_update_another_users_position(self, role, affected_row):
        count, queryset = async_to_sync(self.as_role(role).update)(
            {"id": POSITION_FEES_ID}, BudgetPositionUpdateSchema(sequence=1)
        )
        self.assertEqual(count, affected_row)

    @parameterized.expand([("BUDGET_USER", 0), ("BUDGET_ADMINISTRATOR", 1)])
    def test_delete_another_users_position(self, role, affected_row):
        self.assertEqual(async_to_sync(self.as_role(role).delete)({"id": POSITION_FEES_ID}), affected_row)

    def test_user_cannot_add_to_another_users_budget(self):
        # The budget is resolved through its service: out of scope, it reads as unknown.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.as_role("BUDGET_USER").create)(
                [BudgetPositionCreateSchema(budget=BUDGET_ID2, category=CATEGORY_GENERAL_ID)]
            )

        self.assertEqual(list(ctx.exception.dict()[0]), ["budget"])
