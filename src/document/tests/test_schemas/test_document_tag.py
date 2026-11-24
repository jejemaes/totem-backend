from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from document.schemas import DocumentTagCreateSchema

CATEGORY_ID = "01JD0000000000000000000001"


class DocumentTagSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"category": CATEGORY_ID}, "name"),
            # Required: a tag always sits in a category.
            ("category missing", {"name": "Archived"}, "category"),
            ("category set to null", {"name": "Archived", "category": None}, "category"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            DocumentTagCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])
