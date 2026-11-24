from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.schemas import AccountCategoryCreateSchema, AccountCategoryUpdateSchema


class AccountCategorySchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"color": 1}, "name"),
            # The bound is declared once, as a check constraint and validators on
            # the model field, which become the `ge` and `le` of the field.
            ("color too high", {"name": "Elevenses", "color": 16}, "color"),
            ("color negative", {"name": "Elevenses", "color": -1}, "color"),
            ("account not a ulid", {"name": "Elevenses", "account": 42}, "account"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            AccountCategoryCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([("color too high", {"color": 16}, "color")])
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            AccountCategoryUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_has_no_account(self):
        # The scope of a category is fixed at creation.
        self.assertNotIn("account", AccountCategoryUpdateSchema.model_fields)
