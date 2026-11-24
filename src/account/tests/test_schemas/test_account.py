from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.schemas import AccountCreateSchema, AccountUpdateSchema


class AccountSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            # The `RegexValidator` of the code becomes the pattern of the field.
            ("lower case code", {"code": "shire2", "name": "Hobbiton"}, "code"),
            ("space in code", {"code": "SHIRE 2", "name": "Hobbiton"}, "code"),
            ("code too long", {"code": "A" * 51, "name": "Hobbiton"}, "code"),
            ("code missing", {"name": "Hobbiton"}, "code"),
            ("name missing", {"code": "SHIRE2"}, "name"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            AccountCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand(
        [
            ("lower case code", {"code": "shire"}, "code"),
            ("name set to null", {"name": None}, "name"),
        ]
    )
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            AccountUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([(AccountCreateSchema,), (AccountUpdateSchema,)])
    def test_totals_are_on_no_write_schema(self, schema):
        # Derived from the movements: no request schema carries them.
        self.assertFalse({"total_debit", "total_credit", "balance"} & set(schema.model_fields))
