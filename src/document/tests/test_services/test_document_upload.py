from unittest.mock import patch
from uuid import UUID

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from base.models import FileReference
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from document.choices import DocumentType
from document.models import Document
from document.services import DocumentService
from document.tests.images import image_bytes
from user.tests.test_services.common_user import USER_FRODON_ID, USER_SAM_ID

from document.tests.test_services.common_document import (
    CONTACT_GALADRIEL_ID,
    DocumentServiceCommonMixin,
    upload,
)
from document.tests.test_services.common_document_tag import TAG_SIGNED_ID, TAG_UNKNOWN_ID


class DocumentUploadServiceTest(DocumentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `upload`: one `file` document per file dropped, through `create`, so with
    its access rules, its `validate_data` and its one transaction. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentService, user=self.user_frodon)

    # ------------------------------------------
    # Upload
    # ------------------------------------------

    @parameterized.expand(
        [
            # The common values go to every document of the batch, each relation
            # resolved once for all of them.
            (
                "with common values",
                {"tags": [TAG_SIGNED_ID], "user": USER_SAM_ID, "contact": CONTACT_GALADRIEL_ID},
                14,
                (UUID(USER_SAM_ID), CONTACT_GALADRIEL_ID, [TAG_SIGNED_ID]),
            ),
            # The defaults of `create`: the acting user owns them.
            ("without common values", {}, 10, (UUID(USER_FRODON_ID), None, [])),
        ]
    )
    def test_upload(self, label, common, query_count, expected):
        with self.assertNumQueries(query_count):
            documents = async_to_sync(self.service.upload)([upload("map.pdf"), upload("ring.png", image_bytes())], **common)

        self.assertEqual([document.name for document in documents], ["map.pdf", "ring.png"])
        stored = Document.objects.filter(pk__in=[document.pk for document in documents]).order_by("name")
        self.assertEqual(
            [(document.name, document.document_type, document.mimetype) for document in stored],
            [("map.pdf", DocumentType.FILE, "application/pdf"), ("ring.png", DocumentType.FILE, "image/png")],
        )
        for document in stored:
            self.assertEqual((document.user_id, document.contact_id, list(document.tags.values_list("pk", flat=True))), expected)

    @parameterized.expand(
        [
            # All or nothing, and the error says which file: keyed by its position.
            ("the second file refused", [("map.pdf",), ("logo.svg",), ("ring.png",)], {}, None, 5, {1: ["file"]}),
            # Beyond the count, refused before any query.
            ("too many files", [("map.pdf",), ("ring.png",), ("notes.txt",)], {}, 2, 0, {"files": ["files"]}),
            ("an unknown common tag", [("map.pdf",), ("ring.png",)], {"tags": [TAG_UNKNOWN_ID]}, None, 3, {0: ["tags"], 1: ["tags"]}),
        ]
    )
    def test_upload_invalid(self, label, files, common, max_count, query_count, errors):
        with patch.object(DocumentService, "MAX_UPLOAD_COUNT", max_count or DocumentService.MAX_UPLOAD_COUNT), self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.upload)([upload(*file) for file in files], **common)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        # No row, and no file: the file is committed with the INSERT.
        self.assertEqual(Document.objects.count(), 2)
        self.assertFalse(FileReference.objects.exists())

    def test_upload_nothing(self):
        # Through `create` still: the roles and an empty transaction.
        with self.assertNumQueries(3):
            documents = async_to_sync(self.service.upload)([])

        self.assertEqual((documents, Document.objects.count()), ([], 2))
