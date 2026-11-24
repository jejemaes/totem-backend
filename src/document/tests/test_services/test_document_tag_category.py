from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from document.models import DocumentTag, DocumentTagCategory
from document.schemas import DocumentTagCategoryCreateSchema, DocumentTagCategoryUpdateSchema
from document.services import DocumentTagCategoryService

from document.tests.test_services.common_document_tag import DocumentTagServiceCommonMixin
from document.tests.test_services.common_document_tag_category import (
    CATEGORY_KINGDOM_ID,
    CATEGORY_STATUS_ID,
    CATEGORY_UNKNOWN_ID,
    CATEGORY_YEAR_ID,
)

ALL_CATEGORY_IDS = [CATEGORY_STATUS_ID, CATEGORY_YEAR_ID, CATEGORY_KINGDOM_ID]

NAME_TAKEN = "A tag category with that name already exists."


class DocumentTagCategoryServiceTest(DocumentTagServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `DocumentTagCategoryService`: create, read, update, delete.

    No access rules tests: no `BaseRule` is registered for `DocumentTagCategory`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentTagCategoryService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("required fields only", {"name": "Realm"}, {"color": 0, "sequence": 10}),
            ("every field", {"name": "Realm", "color": 4, "sequence": 1}, {"color": 4, "sequence": 1}),
        ]
    )
    def test_create(self, label, payload, expected_values):
        # The roles, the transaction, the insert, and the access rules checked
        # on the rows written.
        with self.assertNumQueries(5):
            instances = async_to_sync(self.service.create)([DocumentTagCategoryCreateSchema(**payload)])

        self.assertEqual([category.name for category in instances], ["Realm"])
        category = DocumentTagCategory.objects.get(pk=instances[0].pk)
        self.assertEqual({name: getattr(category, name) for name in expected_values}, expected_values)

    @parameterized.expand(
        [
            # A database constraint: keyed on nobody.
            ("name taken", {"name": "Status"}, NAME_TAKEN),
        ]
    )
    def test_create_invalid(self, label, payload, message):
        with self.assertNumQueries(5):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([DocumentTagCategoryCreateSchema(**payload)])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(DocumentTagCategory.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"name": "Realm"}])

        self.assertEqual(DocumentTagCategory.objects.count(), 3)

    # No `test_create_relations`: a category has no relation to write.

    @parameterized.expand(
        [
            ("every input valid", ["Realm", "Author"], None),
            # All or nothing: the valid first input is not written either.
            ("the second input taken", ["Realm", "Year"], "__all__"),
        ]
    )
    def test_create_batch(self, label, names, error_key):
        data = [DocumentTagCategoryCreateSchema(name=name) for name in names]

        with self.assertNumQueries(5):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([category.name for category in instances], names)
            self.assertEqual(DocumentTagCategory.objects.count(), 5)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(DocumentTagCategory.objects.filter(name="Realm").exists())

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(None)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, {"color": 0, "sequence": 10})

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_CATEGORY_IDS),
            ("by name", {"name__icontains": "a"}, [CATEGORY_STATUS_ID, CATEGORY_YEAR_ID]),
            ("with tags", {"tags__isnull": False}, [CATEGORY_STATUS_ID, CATEGORY_STATUS_ID, CATEGORY_YEAR_ID]),
            ("nothing matches", {"name": "Author"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [category.pk for category in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by sequence", ["sequence"], [CATEGORY_STATUS_ID, CATEGORY_YEAR_ID, CATEGORY_KINGDOM_ID]),
            ("by name", ["name"], [CATEGORY_KINGDOM_ID, CATEGORY_STATUS_ID, CATEGORY_YEAR_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [category.pk for category in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    def test_read_fields(self):
        with self.assertNumQueries(2):
            categories = list(async_to_sync(self.service.read)({"id": CATEGORY_STATUS_ID}, fields=["id", "name"]))

        self.assertEqual([category.name for category in categories], ["Status"])
        self.assertIn("color", categories[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("name and color", {"name": "Age", "color": 7}, {"name": "Age", "color": 7, "sequence": 2}),
            ("the sequence", {"sequence": 9}, {"name": "Year", "sequence": 9}),
        ]
    )
    def test_update(self, label, payload, expected_values):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"id": CATEGORY_YEAR_ID}, DocumentTagCategoryUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([category.pk for category in queryset], [CATEGORY_YEAR_ID])
        category = DocumentTagCategory.objects.get(pk=CATEGORY_YEAR_ID)
        self.assertEqual({name: getattr(category, name) for name in expected_values}, expected_values)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": CATEGORY_STATUS_ID}, DocumentTagCategoryUpdateSchema(color=1))

        category = DocumentTagCategory.objects.get(pk=CATEGORY_STATUS_ID)
        self.assertEqual((category.name, category.sequence, category.color), ("Status", 1, 1))

    @parameterized.expand(
        [
            ("name taken", DocumentTagCategoryUpdateSchema(name="Status"), 6, {"__all__": ["__all__"]}),
            # Built unvalidated, as another caller than the API could.
            ("color out of bounds", DocumentTagCategoryUpdateSchema.model_construct(color=16), 0, {0: ["color"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": CATEGORY_YEAR_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        category = DocumentTagCategory.objects.get(pk=CATEGORY_YEAR_ID)
        self.assertEqual((category.name, category.color), ("Year", 0))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": CATEGORY_YEAR_ID}, {"name": "Age"})

        self.assertEqual(DocumentTagCategory.objects.get(pk=CATEGORY_YEAR_ID).name, "Year")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"sequence__gt": 1}, DocumentTagCategoryUpdateSchema(color=2))

        self.assertEqual(count, 2)
        self.assertCountEqual([category.pk for category in queryset], [CATEGORY_YEAR_ID, CATEGORY_KINGDOM_ID])
        self.assertEqual(
            dict(DocumentTagCategory.objects.values_list("pk", "color")),
            {CATEGORY_STATUS_ID: 3, CATEGORY_YEAR_ID: 2, CATEGORY_KINGDOM_ID: 2},
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": CATEGORY_UNKNOWN_ID}, DocumentTagCategoryUpdateSchema(name="Author"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(DocumentTagCategory.objects.filter(name="Author").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a category without tag", {"id": CATEGORY_KINGDOM_ID}, 6, 1),
            ("nothing matches", {"id": CATEGORY_UNKNOWN_ID}, 4, 0),
        ]
    )
    def test_delete(self, label, filters, query_count, affected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(DocumentTagCategory.objects.count(), 3 - affected)

    @parameterized.expand(
        [
            # `DocumentTag.category` is PROTECT: delete or move its tags first.
            ("a category with tags", {"id": CATEGORY_STATUS_ID}),
            ("among others", {"id__in": [CATEGORY_STATUS_ID, CATEGORY_KINGDOM_ID]}),
        ]
    )
    def test_delete_protected(self, label, filters):
        # Refused by the collector, before any DELETE.
        with self.assertNumQueries(6):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.delete)(filters)

        self.assertEqual(ctx.exception.code, "protected_error")
        self.assertIn("DocumentTag.category", str(ctx.exception.dict()["__all__"]))
        self.assertEqual((DocumentTagCategory.objects.count(), DocumentTag.objects.count()), (3, 3))
