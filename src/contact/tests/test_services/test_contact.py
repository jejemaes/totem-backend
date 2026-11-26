from datetime import date

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from contact.models import Contact
from contact.schemas import ContactCreateSchema, ContactFilterSchema, ContactUpdateSchema
from contact.services import ContactService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from contact.tests.test_services.common_contact import (
    CONTACT_ARAGORN_ID,
    CONTACT_BILBON_ID,
    CONTACT_GREEN_DRAGON_ID,
    CONTACT_PONY_ID,
    CONTACT_SAM_ID,
    CONTACT_UNKNOWN_ID,
    ContactServiceCommonMixin,
)
from contact.tests.test_services.common_contact_tag import (
    TAG_FELLOWSHIP_ID,
    TAG_HOBBIT_ID,
    TAG_UNKNOWN_ID,
    TAG_WIZARD_ID,
)

ALL_CONTACT_IDS = [CONTACT_PONY_ID, CONTACT_SAM_ID, CONTACT_ARAGORN_ID, CONTACT_BILBON_ID, CONTACT_GREEN_DRAGON_ID]

VAT_TAKEN = "A company with that VAT number already exists."


class ContactServiceTest(ContactServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `ContactService`: create, read, update, delete. A contact is a person or a
    company, and `validate_data` names the field a type may not fill, which the
    check constraint of the model only reports unkeyed.

    No access rules tests: no `BaseRule` is registered for `Contact`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(ContactService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the transaction, the insert, and the access rules
            # checked on the rows written; each relation given costs its
            # resolution, a many-to-many its write.
            ("a person", {"last_name": "Brandebouc", "first_name": "Merry"}, 5, {"display_name": "Merry Brandebouc", "is_company": False}, []),
            (
                "a person with relations",
                {"last_name": "Touque", "first_name": "Pippin", "country": "SH", "parent": CONTACT_PONY_ID, "tags": [TAG_HOBBIT_ID]},
                9,
                {"country_id": "SH", "parent_id": CONTACT_PONY_ID},
                [TAG_HOBBIT_ID],
            ),
            # A person without first name: no leading space.
            ("a person without first name", {"last_name": "Gollum"}, 5, {"display_name": "Gollum"}, []),
            ("a company", {"is_company": True, "name": "Bag End Ltd", "vat": "BE0999999999"}, 5, {"display_name": "Bag End Ltd", "vat": "BE0999999999"}, []),
        ]
    )
    def test_create(self, label, payload, query_count, expected_values, expected_tags):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([ContactCreateSchema(**payload)])

        self.assertEqual(len(instances), 1)
        contact = Contact.objects.get(pk=instances[0].pk)
        self.assertEqual({name: getattr(contact, name) for name in expected_values}, expected_values)
        self.assertCountEqual(contact.tags.values_list("pk", flat=True), expected_tags)

    @parameterized.expand(
        [
            # `validate_data`, keyed by the index of the payload, naming each field:
            # the roles, a relation given, the transaction, no insert.
            ("a person under a person", {"last_name": "Touque", "parent": CONTACT_SAM_ID}, 5, {0: ["parent"]}),
            ("a person without last name", {"first_name": "Pippin"}, 4, {0: ["last_name"]}),
            ("a person with company fields", {"last_name": "Touque", "vat": "BE0999999999", "name": "Pippin Ltd"}, 4, {0: ["name", "vat"]}),
            ("a company without name", {"is_company": True}, 4, {0: ["name"]}),
            (
                "a company with person fields",
                {"is_company": True, "name": "Took Ltd", "first_name": "Pippin", "birth_date": "2990-01-01", "parent": CONTACT_PONY_ID},
                5,
                {0: ["first_name", "birth_date", "parent"]},
            ),
            # A database constraint: keyed on nobody. Case insensitive.
            ("a vat taken", {"is_company": True, "name": "The Pony Inn", "vat": "be0123456789"}, 5, {"__all__": ["__all__"]}),
        ]
    )
    def test_create_invalid(self, label, payload, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([ContactCreateSchema(**payload)])

        self.assertEqual({key: sorted(value) for key, value in ctx.exception.dict().items()}, {key: sorted(value) for key, value in errors.items()})
        if "__all__" in errors:
            self.assertEqual(ctx.exception.dict()["__all__"]["__all__"], [VAT_TAKEN])
        self.assertEqual(Contact.objects.count(), 5)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"last_name": "Touque"}])

        self.assertEqual(Contact.objects.count(), 5)

    @parameterized.expand(
        [
            # Not checked by the schema, which only types the pk: resolved through
            # the related service, so its access rules apply.
            ("unknown country", {"country": "ZZ"}, 2, "country"),
            ("unknown tag", {"tags": [TAG_UNKNOWN_ID]}, 2, "tags"),
            ("one known tag, one unknown", {"tags": [TAG_HOBBIT_ID, TAG_UNKNOWN_ID]}, 2, "tags"),
            ("unknown company", {"parent": CONTACT_UNKNOWN_ID}, 2, "parent"),
        ]
    )
    def test_create_relations(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([ContactCreateSchema(last_name="Touque", **values)])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Contact.objects.count(), 5)

    @parameterized.expand(
        [
            ("every input valid", [{"last_name": "Touque"}, {"is_company": True, "name": "Took Ltd"}], 5, None),
            # All or nothing: the valid first input is not written either.
            ("the second input invalid", [{"last_name": "Touque"}, {"is_company": True}], 4, {1: ["name"]}),
        ]
    )
    def test_create_batch(self, label, payloads, query_count, errors):
        data = [ContactCreateSchema(**payload) for payload in payloads]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual([contact.display_name for contact in instances], ["Touque", "Took Ltd"])
            self.assertEqual(Contact.objects.count(), 7)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertFalse(Contact.objects.filter(last_name="Touque").exists())

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(None)

        self.assertEqual({name: value for name, value in values.items() if value not in (None, [])}, {"is_company": False})

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_CONTACT_IDS),
            ("a dict", {"display_name__startswith": "The"}, [CONTACT_PONY_ID, CONTACT_GREEN_DRAGON_ID]),
            # The filter schema of the API, with its own lookups.
            ("the companies", ContactFilterSchema(is_company=True), [CONTACT_PONY_ID, CONTACT_GREEN_DRAGON_ID]),
            ("the persons of a company", ContactFilterSchema(parent=CONTACT_PONY_ID), [CONTACT_SAM_ID]),
            ("by tag", ContactFilterSchema(tag=TAG_FELLOWSHIP_ID), [CONTACT_SAM_ID, CONTACT_ARAGORN_ID]),
            ("by country", ContactFilterSchema(country=["GD"]), [CONTACT_ARAGORN_ID]),
            ("without country", ContactFilterSchema(country=["null"]), [CONTACT_PONY_ID, CONTACT_BILBON_ID, CONTACT_GREEN_DRAGON_ID]),
            ("by city", ContactFilterSchema(city="minas"), [CONTACT_ARAGORN_ID]),
            ("nothing matches", ContactFilterSchema(email="sauron"), []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [contact.pk for contact in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            # A generated column: persons and companies sort on one name.
            ("by display name", ["display_name"], [CONTACT_ARAGORN_ID, CONTACT_BILBON_ID, CONTACT_SAM_ID, CONTACT_GREEN_DRAGON_ID, CONTACT_PONY_ID]),
            ("by type, then name", ["-is_company", "display_name"], [CONTACT_GREEN_DRAGON_ID, CONTACT_PONY_ID, CONTACT_ARAGORN_ID, CONTACT_BILBON_ID, CONTACT_SAM_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [contact.pk for contact in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "display_name"], 2, {}),
            # Each relation asked is prefetched with the fields asked on it.
            ("the tags", ["id", "tags__name"], 3, {"tags": ["Fellowship", "Hobbit"]}),
            ("the company and the country", ["id", "parent__display_name", "country__name"], 4, {"parent": "The Prancing Pony", "country": "The Shire"}),
        ]
    )
    def test_read_fields(self, label, fields, query_count, expected):
        with self.assertNumQueries(query_count):
            contacts = list(async_to_sync(self.service.read)({"id": CONTACT_SAM_ID}, fields=fields))
            contact = contacts[0]
            loaded = {
                "tags": sorted(tag.name for tag in contact.tags.all()) if "tags" in expected else None,
                "parent": contact.parent.display_name if "parent" in expected else None,
                "country": contact.country.name if "country" in expected else None,
            }

        self.assertEqual({name: value for name, value in loaded.items() if name in expected}, expected)
        self.assertIn("email", contact.get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a plain field", CONTACT_ARAGORN_ID, {"city": "Osgiliath"}, 5, {"city": "Osgiliath", "display_name": "Aragorn Elessar"}, [TAG_FELLOWSHIP_ID]),
            # The generated name follows a `queryset.update()`.
            ("the name", CONTACT_ARAGORN_ID, {"first_name": "Elessar", "last_name": "Telcontar"}, 5, {"display_name": "Elessar Telcontar"}, [TAG_FELLOWSHIP_ID]),
            ("the tags replaced", CONTACT_SAM_ID, {"tags": [TAG_WIZARD_ID]}, 9, {}, [TAG_WIZARD_ID]),
            ("the tags emptied", CONTACT_SAM_ID, {"tags": []}, 7, {}, []),
            ("a person joining a company", CONTACT_BILBON_ID, {"parent": CONTACT_GREEN_DRAGON_ID}, 6, {"parent_id": CONTACT_GREEN_DRAGON_ID}, []),
            ("a person leaving a company", CONTACT_SAM_ID, {"parent": None}, 5, {"parent_id": None}, [TAG_FELLOWSHIP_ID, TAG_HOBBIT_ID]),
            # The type of a company with no contact may change.
            (
                "a company without contact turned into a person",
                CONTACT_GREEN_DRAGON_ID,
                {"is_company": False, "name": None, "last_name": "Dragon"},
                6,
                {"is_company": False, "display_name": "Dragon"},
                [],
            ),
        ]
    )
    def test_update(self, label, pk, payload, query_count, expected_values, expected_tags):
        before = Contact.objects.get(pk=pk).update_date

        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": pk}, ContactUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([contact.pk for contact in queryset], [pk])
        contact = Contact.objects.get(pk=pk)
        self.assertEqual({name: getattr(contact, name) for name in expected_values}, expected_values)
        self.assertCountEqual(contact.tags.values_list("pk", flat=True), expected_tags)
        # `queryset.update()` bypasses `auto_now`: `ContactQuerySet.update` moves it.
        self.assertGreater(contact.update_date, before)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": CONTACT_BILBON_ID}, ContactUpdateSchema(city="Rivendell"))

        contact = Contact.objects.get(pk=CONTACT_BILBON_ID)
        self.assertEqual(
            (contact.first_name, contact.last_name, contact.birth_date, contact.city),
            ("Bilbon", "Sacquet", date(2890, 9, 22), "Rivendell"),
        )

    @parameterized.expand(
        [
            # `validate_data` during an update: keyed by the pk of the record. Only
            # `vat` is sent: the record says it is a person.
            ("a vat on a person", CONTACT_ARAGORN_ID, ContactUpdateSchema(vat="BE0999999999"), 5, {CONTACT_ARAGORN_ID: ["vat"]}),
            ("a person under a person", CONTACT_BILBON_ID, ContactUpdateSchema(parent=CONTACT_ARAGORN_ID), 6, {CONTACT_BILBON_ID: ["parent"]}),
            # A company turned into a person would leave its persons under a person.
            (
                "a company with contacts turned into a person",
                CONTACT_PONY_ID,
                ContactUpdateSchema(is_company=False, name=None, vat=None, last_name="Butterbur"),
                6,
                {CONTACT_PONY_ID: ["is_company"]},
            ),
            (
                "a company turned into a person of itself",
                CONTACT_GREEN_DRAGON_ID,
                ContactUpdateSchema(is_company=False, name=None, last_name="Dragon", parent=CONTACT_GREEN_DRAGON_ID),
                7,
                {CONTACT_GREEN_DRAGON_ID: ["parent"]},
            ),
            # A database constraint: keyed on nobody.
            ("a vat taken", CONTACT_GREEN_DRAGON_ID, ContactUpdateSchema(vat="BE0123456789"), 6, {"__all__": ["__all__"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("an unknown tag", CONTACT_SAM_ID, ContactUpdateSchema(tags=[TAG_UNKNOWN_ID]), 2, {0: ["tags"]}),
        ]
    )
    def test_update_invalid(self, label, pk, data, query_count, errors):
        before = Contact.objects.get(pk=pk)

        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": pk}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        contact = Contact.objects.get(pk=pk)
        self.assertEqual(
            (contact.is_company, contact.display_name, contact.vat, contact.parent_id),
            (before.is_company, before.display_name, before.vat, before.parent_id),
        )

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": CONTACT_SAM_ID}, {"city": "Bywater"})

        self.assertEqual(Contact.objects.get(pk=CONTACT_SAM_ID).city, "Hobbiton")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)(
                ContactFilterSchema(is_company=False), ContactUpdateSchema(city="Rivendell")
            )

        self.assertEqual(count, 3)
        self.assertCountEqual([contact.pk for contact in queryset], [CONTACT_SAM_ID, CONTACT_ARAGORN_ID, CONTACT_BILBON_ID])
        self.assertEqual(Contact.objects.filter(city="Rivendell").count(), 3)

    def test_update_batch_checks_each_record(self):
        # One payload, a person and a company: the person may not have a VAT.
        with self.assertNumQueries(5):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)(
                    {"id__in": [CONTACT_GREEN_DRAGON_ID, CONTACT_BILBON_ID]}, ContactUpdateSchema(vat="BE0999999999")
                )

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, {CONTACT_BILBON_ID: ["vat"]})
        self.assertFalse(Contact.objects.filter(vat="BE0999999999").exists())

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": CONTACT_UNKNOWN_ID}, ContactUpdateSchema(city="Isengard"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(Contact.objects.filter(city="Isengard").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # The collector also reads the invoices of the contact (PROTECT).
            ("a person with tags", {"id": CONTACT_SAM_ID}, 10, 1, {}),
            # `Contact.parent` is SET_NULL: its persons stay, in no company.
            ("a company with persons", {"id": CONTACT_PONY_ID}, 10, 1, {CONTACT_SAM_ID: None}),
            ("nothing matches", {"id": CONTACT_UNKNOWN_ID}, 4, 0, {CONTACT_SAM_ID: CONTACT_PONY_ID}),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, parents):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(Contact.objects.count(), 5 - affected)
        self.assertFalse(Contact.objects.filter(**filters).exists())
        self.assertEqual({pk: Contact.objects.get(pk=pk).parent_id for pk in parents}, parents)
