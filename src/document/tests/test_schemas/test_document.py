from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from document.schemas import DocumentCreateSchema, DocumentFilterSchema, DocumentUpdateSchema


class DocumentSchemaTest(SimpleTestCase):
    """ What the content must be for its type is not here: `validate_data` checks
    it, before the file reaches the storage. """

    @parameterized.expand(
        [
            ("type missing", {"name": "Letter"}, "document_type"),
            ("type not a choice", {"name": "Letter", "document_type": "scroll"}, "document_type"),
            ("a script in the text", {"name": "Letter", "document_type": "text", "text_content": "<script>alert(1)</script>"}, "text_content"),
            ("date not a date", {"name": "Letter", "document_type": "text", "date": "Third Age"}, "date"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            DocumentCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_has_neither_type_nor_file(self):
        # Replacing a file means creating a new document.
        self.assertFalse({"document_type", "file"} & set(DocumentUpdateSchema.model_fields))

    @parameterized.expand([(DocumentCreateSchema,), (DocumentUpdateSchema,)])
    def test_derived_fields_are_on_no_write_schema(self, schema):
        self.assertFalse({"mimetype", "checksum", "size", "thumbnail"} & set(schema.model_fields))

    @parameterized.expand(
        [
            # `ULID` rather than `str`: a malformed id is refused instead of
            # silently matching nothing.
            ("tag not a ulid", {"tag": "draft"}, "tag"),
            ("tag category not a ulid", {"tag_category": "status"}, "tag_category"),
            ("contact not a ulid", {"contact": "elrond"}, "contact"),
        ]
    )
    def test_filter_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            DocumentFilterSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])
