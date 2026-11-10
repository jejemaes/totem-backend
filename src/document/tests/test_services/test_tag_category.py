from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from document.models import DocumentTagCategory
from document.schemas import DocumentTagCategoryCreateSchema, DocumentTagCategoryUpdateSchema
from document.services import DocumentTagCategoryService
from document.tests.common import (
    CATEGORY_EMPTY_ID,
    CATEGORY_STATUS_ID,
    CATEGORY_YEAR_ID,
    DocumentTestMixin,
)


class TestDocumentTagCategoryService(DocumentTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(DocumentTagCategoryService)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("missing name", {"color": 1}),
            ("color too high", {"name": "Realm", "color": 16}),
            ("color negative", {"name": "Realm", "color": -1}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertRaises(PydanticValidationError):
            DocumentTagCategoryCreateSchema(**payload)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_valid(self):
        instances = async_to_sync(self.service.create)(
            [DocumentTagCategoryCreateSchema(name="Realm", color=4)]
        )
        category = DocumentTagCategory.objects.get(pk=instances[0].pk)
        self.assertEqual((category.name, category.color, category.sequence), ("Realm", 4, 10))

    def test_create_name_taken(self):
        # A unique constraint is reported by the database, for the whole write.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([DocumentTagCategoryCreateSchema(name="Status")])
        self.assertIn("__all__", ctx.exception.dict()["__all__"])

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_update_valid(self):
        count, queryset = async_to_sync(self.service.update)(
            {"id": CATEGORY_YEAR_ID}, DocumentTagCategoryUpdateSchema(name="Age", color=7)
        )
        self.assertEqual(count, 1)
        category = DocumentTagCategory.objects.get(pk=CATEGORY_YEAR_ID)
        self.assertEqual((category.name, category.color), ("Age", 7))

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete_without_tags(self):
        self.assertEqual(async_to_sync(self.service.delete)({"id": CATEGORY_EMPTY_ID}), 1)
        self.assertFalse(DocumentTagCategory.objects.filter(pk=CATEGORY_EMPTY_ID).exists())

    def test_delete_with_tags_is_refused(self):
        # `PROTECT`: the tags, and their links to the documents, are not taken along.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.delete)({"id": CATEGORY_STATUS_ID})
        self.assertEqual(ctx.exception.code, "protected_error")
        self.assertTrue(DocumentTagCategory.objects.filter(pk=CATEGORY_STATUS_ID).exists())

    # ------------------------------------------
    # Tests Resequence
    # ------------------------------------------

    def test_resequence(self):
        async_to_sync(self.service.resequence)([CATEGORY_YEAR_ID, CATEGORY_EMPTY_ID, CATEGORY_STATUS_ID])
        self.assertEqual(
            list(DocumentTagCategory.objects.order_by("sequence").values_list("id", flat=True)),
            [CATEGORY_YEAR_ID, CATEGORY_EMPTY_ID, CATEGORY_STATUS_ID],
        )
