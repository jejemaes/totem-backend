from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from website.schemas import MenuCreateSchema, MenuUpdateSchema


class MenuSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"link": "/bree/"}, "name"),
            # A relation borrows the constraints of the target primary key.
            ("parent too long for a ulid", {"name": "Bree", "parent": "0" * 27}, "parent"),
            ("sequence not a number", {"name": "Bree", "sequence": "first"}, "sequence"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            MenuCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([(MenuCreateSchema,), (MenuUpdateSchema,)])
    def test_path_is_on_no_write_schema(self, schema):
        # Materialized by `MenuQuerySet`, never written by a client.
        self.assertNotIn("parent_path", schema.model_fields)
