from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.schemas import BudgetPositionCreateSchema, BudgetPositionUpdateSchema

BUDGET_ID = "01JB0000000000000000000001"
CATEGORY_ID = "01JC0000000000000000000001"


class BudgetPositionSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("budget missing", {"category": CATEGORY_ID}, "budget"),
            ("category missing", {"budget": BUDGET_ID}, "category"),
            ("sequence not a number", {"budget": BUDGET_ID, "category": CATEGORY_ID, "sequence": "first"}, "sequence"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            BudgetPositionCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_has_no_budget(self):
        # A position does not move to another budget.
        self.assertNotIn("budget", BudgetPositionUpdateSchema.model_fields)

    @parameterized.expand([(BudgetPositionCreateSchema,), (BudgetPositionUpdateSchema,)])
    def test_computed_fields_are_on_no_write_schema(self, schema):
        self.assertFalse({"name", "color", "total_planned", "total_practical"} & set(schema.model_fields))
