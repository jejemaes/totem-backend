from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from document.schemas import DocumentTagCategoryCreateSchema, DocumentTagCategoryUpdateSchema


class DocumentTagCategorySchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"color": 1}, "name"),
            ("color too high", {"name": "Realm", "color": 16}, "color"),
            ("color negative", {"name": "Realm", "color": -1}, "color"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            DocumentTagCategoryCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([("color too high", {"color": 16}, "color")])
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            DocumentTagCategoryUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])
