from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from document.models import Document, DocumentTag
from document.schemas import DocumentTagCreateSchema, DocumentTagUpdateSchema
from document.services import DocumentTagService

from document.tests.test_services.common_document import (
    DOCUMENT_MINUTES_ID,
    DOCUMENT_NOTES_ID,
    DocumentServiceCommonMixin,
)
from document.tests.test_services.common_document_tag import (
    TAG_2026_ID,
    TAG_DRAFT_ID,
    TAG_SIGNED_ID,
    TAG_UNKNOWN_ID,
)
from document.tests.test_services.common_document_tag_category import (
    CATEGORY_KINGDOM_ID,
    CATEGORY_STATUS_ID,
    CATEGORY_UNKNOWN_ID,
    CATEGORY_YEAR_ID,
)

ALL_TAG_IDS = [TAG_DRAFT_ID, TAG_SIGNED_ID, TAG_2026_ID]

NAME_TAKEN = "This category already has a tag with that name."


class DocumentTagServiceTest(DocumentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `DocumentTagService`: create, read, update, delete.

    No access rules tests: no `BaseRule` is registered for `DocumentTag`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentTagService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("in a category", {"name": "Archived", "category": CATEGORY_STATUS_ID}, {"category_id": CATEGORY_STATUS_ID, "sequence": 10}),
            # Unique within a category only.
            ("a name of another category", {"name": "Draft", "category": CATEGORY_YEAR_ID}, {"category_id": CATEGORY_YEAR_ID}),
            ("with a sequence", {"name": "Gondor", "category": CATEGORY_KINGDOM_ID, "sequence": 1}, {"sequence": 1}),
        ]
    )
    def test_create(self, label, payload, expected_values):
        # The roles, the category, the transaction, the insert, and the access
        # rules checked on the rows written.
        with self.assertNumQueries(6):
            instances = async_to_sync(self.service.create)([DocumentTagCreateSchema(**payload)])

        self.assertEqual([tag.name for tag in instances], [payload["name"]])
        tag = DocumentTag.objects.get(pk=instances[0].pk)
        self.assertEqual({name: getattr(tag, name) for name in expected_values}, expected_values)

    @parameterized.expand(
        [
            # A database constraint: keyed on nobody.
            ("name taken in the category", {"name": "Draft", "category": CATEGORY_STATUS_ID}, NAME_TAKEN),
        ]
    )
    def test_create_invalid(self, label, payload, message):
        with self.assertNumQueries(6):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([DocumentTagCreateSchema(**payload)])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(DocumentTag.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"name": "Archived", "category": CATEGORY_STATUS_ID}])

        self.assertEqual(DocumentTag.objects.count(), 3)

    def test_create_relations(self):
        # The roles, then the category asked, before the transaction.
        with self.assertNumQueries(2):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([DocumentTagCreateSchema(name="Archived", category=CATEGORY_UNKNOWN_ID)])

        self.assertEqual(list(ctx.exception.dict()[0]), ["category"])
        self.assertEqual(DocumentTag.objects.count(), 3)

    @parameterized.expand(
        [
            ("every input valid", [("Archived", CATEGORY_STATUS_ID), ("Gondor", CATEGORY_KINGDOM_ID)], 6, None),
            ("the second input taken", [("Archived", CATEGORY_STATUS_ID), ("2026", CATEGORY_YEAR_ID)], 6, "__all__"),
        ]
    )
    def test_create_batch(self, label, tags, query_count, error_key):
        data = [DocumentTagCreateSchema(name=name, category=category) for name, category in tags]

        with self.assertNumQueries(query_count):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([tag.name for tag in instances], ["Archived", "Gondor"])
            self.assertEqual(DocumentTag.objects.count(), 5)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(DocumentTag.objects.filter(name="Archived").exists())

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(None)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, {"sequence": 10})

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_TAG_IDS),
            ("of a category", {"category": CATEGORY_STATUS_ID}, [TAG_DRAFT_ID, TAG_SIGNED_ID]),
            ("on a document", {"documents": DOCUMENT_NOTES_ID}, [TAG_DRAFT_ID, TAG_2026_ID]),
            ("nothing matches", {"category": CATEGORY_KINGDOM_ID}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [tag.pk for tag in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by sequence, descending", ["-sequence"], [TAG_2026_ID, TAG_SIGNED_ID, TAG_DRAFT_ID]),
            ("by name", ["name"], [TAG_2026_ID, TAG_DRAFT_ID, TAG_SIGNED_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [tag.pk for tag in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    def test_read_fields(self):
        # The category is prefetched, with the fields asked on it.
        with self.assertNumQueries(3):
            tags = list(async_to_sync(self.service.read)({"id": TAG_2026_ID}, fields=["id", "name", "category__name"]))
            category_name = tags[0].category.name

        self.assertEqual(([tag.name for tag in tags], category_name), (["2026"], "Year"))
        self.assertIn("sequence", tags[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the name", {"name": "Proposal"}, 5, {"name": "Proposal", "category_id": CATEGORY_STATUS_ID}),
            ("moved to another category", {"category": CATEGORY_YEAR_ID}, 6, {"category_id": CATEGORY_YEAR_ID}),
        ]
    )
    def test_update(self, label, payload, query_count, expected_values):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": TAG_DRAFT_ID}, DocumentTagUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([tag.pk for tag in queryset], [TAG_DRAFT_ID])
        tag = DocumentTag.objects.get(pk=TAG_DRAFT_ID)
        self.assertEqual({name: getattr(tag, name) for name in expected_values}, expected_values)
        # The documents keep it, wherever it goes.
        self.assertEqual(list(tag.documents.values_list("pk", flat=True)), [DOCUMENT_NOTES_ID])

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": TAG_SIGNED_ID}, DocumentTagUpdateSchema(sequence=5))

        tag = DocumentTag.objects.get(pk=TAG_SIGNED_ID)
        self.assertEqual((tag.name, tag.category_id, tag.sequence), ("Signed", CATEGORY_STATUS_ID, 5))

    @parameterized.expand(
        [
            ("name taken in the category", DocumentTagUpdateSchema(name="Signed"), 6, {"__all__": ["__all__"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown category", DocumentTagUpdateSchema(category=CATEGORY_UNKNOWN_ID), 2, {0: ["category"]}),
            # Built unvalidated, as another caller than the API could.
            ("category set to null", DocumentTagUpdateSchema.model_construct(category=None), 0, {0: ["category"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": TAG_DRAFT_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        tag = DocumentTag.objects.get(pk=TAG_DRAFT_ID)
        self.assertEqual((tag.name, tag.category_id), ("Draft", CATEGORY_STATUS_ID))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": TAG_DRAFT_ID}, {"name": "Proposal"})

        self.assertEqual(DocumentTag.objects.get(pk=TAG_DRAFT_ID).name, "Draft")

    def test_update_batch(self):
        with self.assertNumQueries(6):
            count, queryset = async_to_sync(self.service.update)({"category": CATEGORY_STATUS_ID}, DocumentTagUpdateSchema(category=CATEGORY_KINGDOM_ID))

        self.assertEqual(count, 2)
        self.assertCountEqual([tag.pk for tag in queryset], [TAG_DRAFT_ID, TAG_SIGNED_ID])
        self.assertCountEqual(DocumentTag.objects.filter(category_id=CATEGORY_KINGDOM_ID).values_list("pk", flat=True), [TAG_DRAFT_ID, TAG_SIGNED_ID])

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": TAG_UNKNOWN_ID}, DocumentTagUpdateSchema(name="Proposal"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(DocumentTag.objects.filter(name="Proposal").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # The documents stay, and lose the tag.
            ("a tag in use", {"id": TAG_DRAFT_ID}, 6, 1, {DOCUMENT_NOTES_ID: [TAG_2026_ID], DOCUMENT_MINUTES_ID: [TAG_SIGNED_ID]}),
            ("a whole category's", {"category": CATEGORY_STATUS_ID}, 6, 2, {DOCUMENT_NOTES_ID: [TAG_2026_ID], DOCUMENT_MINUTES_ID: []}),
            ("nothing matches", {"id": TAG_UNKNOWN_ID}, 4, 0, {DOCUMENT_NOTES_ID: [TAG_2026_ID, TAG_DRAFT_ID], DOCUMENT_MINUTES_ID: [TAG_SIGNED_ID]}),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, tags_by_document):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(Document.objects.count(), 2)
        self.assertEqual(
            {pk: sorted(Document.objects.get(pk=pk).tags.values_list("pk", flat=True)) for pk in tags_by_document},
            {pk: sorted(tags) for pk, tags in tags_by_document.items()},
        )
