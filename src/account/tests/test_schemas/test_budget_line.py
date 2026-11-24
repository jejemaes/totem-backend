from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.schemas import BudgetLineCreateSchema, BudgetLineUpdateSchema

PAYLOAD = {
    "budget": "01JB0000000000000000000001",
    "position": "01JP0000000000000000000001",
    "name": "Mushrooms",
    "planned_amount": "-500",
}


class BudgetLineSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", "name", None, "name"),
            ("position missing", "position", None, "position"),
            ("amount missing", "planned_amount", None, "planned_amount"),
            ("too many decimals", "planned_amount", "1.001", "planned_amount"),
        ]
    )
    def test_create_schema_invalid(self, label, name, value, field):
        payload = {key: val for key, val in PAYLOAD.items() if key != name}
        if value is not None:
            payload[name] = value

        with self.assertRaises(PydanticValidationError) as ctx:
            BudgetLineCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_has_no_budget(self):
        # Derived from the position, never written by a client.
        self.assertNotIn("budget", BudgetLineUpdateSchema.model_fields)
