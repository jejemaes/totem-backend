from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from website.schemas import MediaCreateSchema


class MediaSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("content missing", {}),
            # The factory would type a `FileField` as `str`, which cannot carry
            # bytes: the explicit `UploadedFile` annotation is what refuses it.
            ("a path instead of a file", {"content": "website/2026/09/red-book.pdf"}),
        ]
    )
    def test_create_schema_invalid(self, label, payload):
        with self.assertRaises(PydanticValidationError) as ctx:
            MediaCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], ["content"])

    def test_only_the_content_is_writable(self):
        # Letting a caller set `checksum`, `name` or `mimetype` would let it lie
        # about what it uploaded.
        self.assertEqual(set(MediaCreateSchema.model_fields), {"content"})
