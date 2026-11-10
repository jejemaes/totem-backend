from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from parameterized import parameterized

from base.files.validation import validate_upload
from core.services.exceptions import ServiceValidationError


class TestValidateUpload(SimpleTestCase):

    @parameterized.expand([
        ("photo.png", b"x" * 10),
        ("report.pdf", b"x" * 10),
        # At the limit: the maximum itself is allowed.
        ("limit.png", b"x" * 16),
        # No extension, no guess: nothing to refuse.
        ("README", b"x" * 10),
    ])
    def test_validate_upload_accepted(self, name, content):
        validate_upload(SimpleUploadedFile(name, content), 16, key="file")

    @parameterized.expand([
        ("huge.png", b"x" * 17),
        ("logo.svg", b"<svg/>"),
        ("page.html", b"<html/>"),
        ("feed.xml", b"<xml/>"),
        # The filename decides, not the declared content type: see the module.
        ("disguised.svg", b"<svg/>", "image/png"),
    ])
    def test_validate_upload_refused(self, name, content, content_type="application/octet-stream"):
        upload = SimpleUploadedFile(name, content, content_type=content_type)
        with self.assertRaises(ServiceValidationError) as ctx:
            validate_upload(upload, 16, key="file")
        # Keyed on the field given, so the error lands on that field of the payload.
        self.assertEqual(list(ctx.exception.message_dict), ["file"])
