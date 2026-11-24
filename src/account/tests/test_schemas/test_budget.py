from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.schemas import BudgetCreateSchema, BudgetUpdateSchema

ACCOUNT_ID = "01JA0000000000000000000001"


class BudgetSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"account": ACCOUNT_ID}, "name"),
            ("account missing", {"name": "Bag End 2027"}, "account"),
            ("user not a uuid4", {"name": "Bag End 2027", "account": ACCOUNT_ID, "user": "00000000-0000-0000-0000-000000000000"}, "user"),
            # `HtmlField`: a script is refused, not cleaned.
            ("script in the note", {"name": "Bag End 2027", "account": ACCOUNT_ID, "note": "<script>alert(1)</script>"}, "note"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            BudgetCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([("script in the note", {"note": "<script>alert(1)</script>"}, "note")])
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            BudgetUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_has_no_account(self):
        # The positions were chosen among the categories of that account.
        self.assertNotIn("account", BudgetUpdateSchema.model_fields)

    @parameterized.expand([(BudgetCreateSchema,), (BudgetUpdateSchema,)])
    def test_totals_are_on_no_write_schema(self, schema):
        self.assertFalse(
            {"total_planned_amount", "total_practical_amount", "uncategorized_movement_count"} & set(schema.model_fields)
        )
