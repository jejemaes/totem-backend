from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from contact.schemas import ContactTagCreateSchema, ContactTagUpdateSchema


class ContactTagSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"color": 3}, "name"),
            # Declared once, as validators on the model field: `convert_validators`
            # turns them into the `ge` and `le` of the pydantic field.
            ("color too high", {"name": "Dwarf", "color": 16}, "color"),
            ("color negative", {"name": "Dwarf", "color": -1}, "color"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            ContactTagCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([(0,), (15,)])
    def test_create_schema_color_bounds_are_inclusive(self, color):
        self.assertEqual(ContactTagCreateSchema(name="Dwarf", color=color).color, color)

    @parameterized.expand([("color too high", {"color": 16}, "color")])
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            ContactTagUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])
