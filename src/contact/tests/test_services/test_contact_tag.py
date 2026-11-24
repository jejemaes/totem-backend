from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from contact.models import Contact, ContactTag
from contact.schemas import ContactTagCreateSchema, ContactTagFilterSchema, ContactTagUpdateSchema
from contact.services import ContactTagService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from contact.tests.test_services.common_contact import CONTACT_ARAGORN_ID, CONTACT_SAM_ID, ContactServiceCommonMixin
from contact.tests.test_services.common_contact_tag import (
    TAG_FELLOWSHIP_ID,
    TAG_HOBBIT_ID,
    TAG_UNKNOWN_ID,
    TAG_WIZARD_ID,
)

ALL_TAG_IDS = [TAG_FELLOWSHIP_ID, TAG_HOBBIT_ID, TAG_WIZARD_ID]

NAME_TAKEN = "A tag with that name already exists."


class ContactTagServiceTest(ContactServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `ContactTagService`: create, read, update, delete.

    No access rules tests: no `BaseRule` is registered for `ContactTag`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(ContactTagService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("required fields only", {"name": "Dwarf"}, {"color": 0}),
            ("with a color", {"name": "Dwarf", "color": 15}, {"color": 15}),
        ]
    )
    def test_create(self, label, payload, expected_values):
        # The roles, the transaction, the insert, and the access rules checked
        # on the rows written.
        with self.assertNumQueries(5):
            instances = async_to_sync(self.service.create)([ContactTagCreateSchema(**payload)])

        self.assertEqual([tag.name for tag in instances], [payload["name"]])
        tag = ContactTag.objects.get(pk=instances[0].pk)
        self.assertEqual({name: getattr(tag, name) for name in ["name", *expected_values]}, {"name": payload["name"], **expected_values})

    @parameterized.expand(
        [
            ("name taken", {"name": "Hobbit"}, NAME_TAKEN),
            # The uniqueness ignores the case.
            ("name taken, in another case", {"name": "hobbit"}, NAME_TAKEN),
        ]
    )
    def test_create_invalid(self, label, payload, message):
        with self.assertNumQueries(5):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([ContactTagCreateSchema(**payload)])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(ContactTag.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"name": "Dwarf"}])

        self.assertEqual(ContactTag.objects.count(), 3)

    # No `test_create_relations`: a tag has no relation to write.

    @parameterized.expand(
        [
            ("every input valid", ["Dwarf", "Elf"], 5, None),
            # All or nothing: the valid first input is not written either.
            ("the second input taken", ["Dwarf", "Wizard"], 5, "__all__"),
        ]
    )
    def test_create_batch(self, label, names, query_count, error_key):
        data = [ContactTagCreateSchema(name=name) for name in names]

        with self.assertNumQueries(query_count):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([tag.name for tag in instances], names)
            self.assertEqual(ContactTag.objects.count(), 5)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(ContactTag.objects.filter(name="Dwarf").exists())

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(None)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, {"color": 0})

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_TAG_IDS),
            ("a dict", {"color__gt": 4}, [TAG_HOBBIT_ID, TAG_WIZARD_ID]),
            # The filter schema of the API, with its own lookups.
            ("by name", ContactTagFilterSchema(name="IZ"), [TAG_WIZARD_ID]),
            ("by a search term", ContactTagFilterSchema(search="ship"), [TAG_FELLOWSHIP_ID]),
            ("nothing matches", ContactTagFilterSchema(name="Orc"), []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [tag.pk for tag in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by name", ["name"], [TAG_FELLOWSHIP_ID, TAG_HOBBIT_ID, TAG_WIZARD_ID]),
            ("by color, descending", ["-color"], [TAG_WIZARD_ID, TAG_HOBBIT_ID, TAG_FELLOWSHIP_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [tag.pk for tag in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    def test_read_fields(self):
        with self.assertNumQueries(2):
            tags = list(async_to_sync(self.service.read)({"id": TAG_HOBBIT_ID}, fields=["id", "name"]))

        self.assertEqual([tag.name for tag in tags], ["Hobbit"])
        self.assertIn("color", tags[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the name", {"name": "Halfling"}, {"name": "Halfling", "color": 5}),
            ("the color", {"color": 0}, {"name": "Hobbit", "color": 0}),
        ]
    )
    def test_update(self, label, payload, expected_values):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"id": TAG_HOBBIT_ID}, ContactTagUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([tag.pk for tag in queryset], [TAG_HOBBIT_ID])
        tag = ContactTag.objects.get(pk=TAG_HOBBIT_ID)
        self.assertEqual({name: getattr(tag, name) for name in expected_values}, expected_values)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": TAG_WIZARD_ID}, ContactTagUpdateSchema(color=1))

        tag = ContactTag.objects.get(pk=TAG_WIZARD_ID)
        self.assertEqual((tag.name, tag.color), ("Wizard", 1))

    @parameterized.expand(
        [
            ("name taken", ContactTagUpdateSchema(name="Wizard"), 6, {"__all__": ["__all__"]}),
            # Built unvalidated, as another caller than the API could: the bound is
            # a validator of the model field, enforced by `to_internal_values`.
            ("color out of bounds", ContactTagUpdateSchema.model_construct(color=16), 0, {0: ["color"]}),
            ("name set to null", ContactTagUpdateSchema.model_construct(name=None), 0, {0: ["name"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": TAG_HOBBIT_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        tag = ContactTag.objects.get(pk=TAG_HOBBIT_ID)
        self.assertEqual((tag.name, tag.color), ("Hobbit", 5))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": TAG_HOBBIT_ID}, {"color": 1})

        self.assertEqual(ContactTag.objects.get(pk=TAG_HOBBIT_ID).color, 5)

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"color__gt": 4}, ContactTagUpdateSchema(color=1))

        self.assertEqual(count, 2)
        self.assertCountEqual([tag.pk for tag in queryset], [TAG_HOBBIT_ID, TAG_WIZARD_ID])
        self.assertEqual(
            dict(ContactTag.objects.values_list("pk", "color")),
            {TAG_FELLOWSHIP_ID: 3, TAG_HOBBIT_ID: 1, TAG_WIZARD_ID: 1},
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": TAG_UNKNOWN_ID}, ContactTagUpdateSchema(name="Orc"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(ContactTag.objects.filter(name="Orc").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # Pinned as found: a tag still in use goes, the contacts lose it.
            ("a tag in use", {"id": TAG_FELLOWSHIP_ID}, 6, 1, {CONTACT_SAM_ID: [TAG_HOBBIT_ID], CONTACT_ARAGORN_ID: []}),
            ("a tag on nobody", {"id": TAG_WIZARD_ID}, 6, 1, {CONTACT_SAM_ID: [TAG_FELLOWSHIP_ID, TAG_HOBBIT_ID], CONTACT_ARAGORN_ID: [TAG_FELLOWSHIP_ID]}),
            ("nothing matches", {"id": TAG_UNKNOWN_ID}, 4, 0, {CONTACT_SAM_ID: [TAG_FELLOWSHIP_ID, TAG_HOBBIT_ID], CONTACT_ARAGORN_ID: [TAG_FELLOWSHIP_ID]}),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, tags_by_contact):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(ContactTag.objects.count(), 3 - affected)
        self.assertEqual(
            {pk: sorted(Contact.objects.get(pk=pk).tags.values_list("pk", flat=True)) for pk in tags_by_contact},
            tags_by_contact,
        )
