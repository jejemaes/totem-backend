from asgiref.sync import async_to_sync
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from document.models import Document, DocumentTag
from document.schemas import DocumentTagCreateSchema, DocumentTagUpdateSchema
from document.services import DocumentTagService
from document.tests.common import (
    CATEGORY_STATUS_ID,
    CATEGORY_YEAR_ID,
    DOCUMENT_NOTES_ID,
    TAG_2026_ID,
    TAG_DRAFT_ID,
    TAG_SIGNED_ID,
    DocumentTestMixin,
)


class TestDocumentTagService(DocumentTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(DocumentTagService)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_valid(self):
        instances = async_to_sync(self.service.create)(
            [DocumentTagCreateSchema(name="Archived", category=CATEGORY_STATUS_ID)]
        )
        self.assertEqual(DocumentTag.objects.get(pk=instances[0].pk).category_id, CATEGORY_STATUS_ID)

    def test_create_same_name_in_another_category(self):
        async_to_sync(self.service.create)(
            [DocumentTagCreateSchema(name="Draft", category=CATEGORY_YEAR_ID)]
        )
        self.assertEqual(DocumentTag.objects.filter(name="Draft").count(), 2)

    def test_create_name_taken_in_the_category(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)(
                [DocumentTagCreateSchema(name="Draft", category=CATEGORY_STATUS_ID)]
            )
        self.assertIn("__all__", ctx.exception.dict()["__all__"])

    def test_create_unknown_category(self):
        # Resolved through the category's service, per payload: keyed by its index.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)(
                [DocumentTagCreateSchema(name="Archived", category="01JD0000000000000000000099")]
            )
        self.assertEqual(list(ctx.exception.dict()[0]), ["category"])

    def test_create_without_category_is_rejected_when_building_the_schema(self):
        # A tag always has a category: the column is NOT NULL, so is the field.
        with self.assertRaises(PydanticValidationError):
            DocumentTagCreateSchema(name="Archived", category=None)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_update_moves_the_tag_to_another_category(self):
        async_to_sync(self.service.update)(
            {"id": TAG_DRAFT_ID}, DocumentTagUpdateSchema(category=CATEGORY_YEAR_ID)
        )
        self.assertEqual(DocumentTag.objects.get(pk=TAG_DRAFT_ID).category_id, CATEGORY_YEAR_ID)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete_unlinks_the_documents(self):
        async_to_sync(self.service.delete)({"id": TAG_DRAFT_ID})
        self.assertEqual(
            list(Document.objects.get(pk=DOCUMENT_NOTES_ID).tags.values_list("id", flat=True)),
            [TAG_2026_ID],
        )

    # ------------------------------------------
    # Tests Resequence
    # ------------------------------------------

    def test_resequence_within_a_category(self):
        async_to_sync(self.service.resequence)([TAG_SIGNED_ID, TAG_DRAFT_ID])
        self.assertEqual(
            list(
                DocumentTag.objects.filter(category_id=CATEGORY_STATUS_ID)
                .order_by("sequence")
                .values_list("id", flat=True)
            ),
            [TAG_SIGNED_ID, TAG_DRAFT_ID],
        )
