from asgiref.sync import async_to_sync
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from base.models import Country
from contact.models import Contact, ContactTag
from contact.schemas import (
    ContactCreateSchema,
    ContactTagCreateSchema,
    ContactUpdateSchema,
)
from contact.services import ContactService, ContactTagService
from core.services import DeleteMixin, Environment, ServiceBase
from core.services.exceptions import ServiceValidationMultiError
from core.services.registry import ServiceRegistry


class TestContactService(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(code="BE", name="Belgium")
        cls.tag_vip = ContactTag.objects.create(name="VIP", color=3)
        cls.tag_family = ContactTag.objects.create(name="Family", color=5)

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(ContactService)

    def test_create_resolves_relations(self):
        contacts = async_to_sync(self.service.create)([
            ContactCreateSchema(
                last_name="Tournesol",
                first_name="Tryphon",
                city="Moulinsart",
                country="BE",
                tags=[self.tag_vip.pk],
            )
        ])

        self.assertEqual(len(contacts), 1)
        contact = Contact.objects.get(pk=contacts[0].pk)
        self.assertEqual(contact.country, self.country)
        self.assertEqual([t.pk for t in contact.tags.all()], [self.tag_vip.pk])

    def test_create_with_unknown_country(self):
        # Relations are not checked by the schema, which only types the primary
        # key: `to_internal_values` resolves them through the related service, so
        # that access rules apply to what a payload is allowed to point at.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([
                ContactCreateSchema(last_name="Tournesol", country="ZZ")
            ])

        self.assertIn("country", ctx.exception.dict()[0])
        self.assertFalse(Contact.objects.exists())

    def test_create_with_unknown_tag(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([
                ContactCreateSchema(
                    last_name="Tournesol", tags=["01ARZ3NDEKTSV4RRFFQ69G5FAV"]
                )
            ])

        self.assertIn("tags", ctx.exception.dict()[0])
        self.assertFalse(Contact.objects.exists())

    def test_update_moves_update_date(self):
        contact = Contact.objects.create(last_name="Tournesol")
        update_date = contact.update_date

        async_to_sync(self.service.update)(
            {"id": contact.pk}, ContactUpdateSchema(city="Bruxelles")
        )

        contact.refresh_from_db()
        self.assertEqual(contact.city, "Bruxelles")
        # Regression guard: the service updates through `queryset.update()`, which
        # bypasses the `auto_now` of the field.
        self.assertGreater(contact.update_date, update_date)

    def test_update_replaces_tags(self):
        contact = Contact.objects.create(last_name="Tournesol")
        contact.tags.set([self.tag_vip])

        async_to_sync(self.service.update)(
            {"id": contact.pk}, ContactUpdateSchema(tags=[self.tag_family.pk])
        )

        self.assertEqual(
            [t.pk for t in contact.tags.all()], [self.tag_family.pk]
        )

    def test_read_with_filters(self):
        Contact.objects.create(last_name="Tournesol", country=self.country)
        Contact.objects.create(last_name="Haddock")

        queryset = async_to_sync(self.service.read)({"country": self.country})

        self.assertEqual([c.last_name for c in queryset], ["Tournesol"])

    def test_delete(self):
        contact = Contact.objects.create(last_name="Tournesol")

        async_to_sync(self.service.delete)({"id": contact.pk})

        self.assertFalse(Contact.objects.filter(pk=contact.pk).exists())


class TestContactCompanyService(TestCase):
    """`validate_data`: the type of a contact decides which fields it may fill.

    Errors of a creation are keyed by the payload's index, those of an update by
    the record's pk.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Contact.objects.create(is_company=True, name="Moulinsart SA")
        cls.person = Contact.objects.create(last_name="Haddock", parent=cls.company)

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(ContactService)

    def test_create_a_person_in_a_company(self):
        contacts = async_to_sync(self.service.create)([
            ContactCreateSchema(last_name="Tournesol", parent=self.company.pk)
        ])

        self.assertEqual(Contact.objects.get(pk=contacts[0].pk).parent, self.company)

    def test_create_a_person_under_a_person(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([
                ContactCreateSchema(last_name="Tournesol", parent=self.person.pk)
            ])

        self.assertEqual(list(ctx.exception.dict()[0]), ["parent"])

    def test_create_a_company_with_person_fields(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([
                ContactCreateSchema(
                    is_company=True, name="Labo SPRL", first_name="Tryphon", parent=self.company.pk
                )
            ])

        self.assertCountEqual(ctx.exception.dict()[0], ["first_name", "parent"])

    def test_update_keeps_the_type_of_the_record(self):
        # Only `vat` is sent: the record says it is a person.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": self.person.pk}, ContactUpdateSchema(vat="BE0123456789")
            )

        self.assertEqual(list(ctx.exception.dict()[self.person.pk]), ["vat"])

    def test_update_a_company_without_contacts_to_a_person(self):
        company = Contact.objects.create(is_company=True, name="Labo SPRL")

        async_to_sync(self.service.update)(
            {"id": company.pk},
            ContactUpdateSchema(is_company=False, name=None, last_name="Tournesol"),
        )

        company.refresh_from_db()
        self.assertFalse(company.is_company)
        self.assertEqual(company.display_name, "Tournesol")

    def test_update_a_company_with_contacts_to_a_person(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": self.company.pk},
                ContactUpdateSchema(is_company=False, name=None, last_name="Moulinsart"),
            )

        self.assertEqual(list(ctx.exception.dict()[self.company.pk]), ["is_company"])


class TestContactTagService(TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(ContactTagService)

    def test_create(self):
        tags = async_to_sync(self.service.create)([
            ContactTagCreateSchema(name="VIP", color=3)
        ])

        self.assertEqual(len(tags), 1)
        self.assertEqual(len(tags[0].pk), 26)

    def test_color_upper_bound_is_rejected_by_the_schema(self):
        # The bound is declared once, as a django validator on the model field;
        # `convert_validators` turns it into the `le` of the pydantic field.
        with self.assertRaises(PydanticValidationError):
            ContactTagCreateSchema(name="Bad", color=16)

    def test_color_lower_bound_is_rejected_by_the_schema(self):
        with self.assertRaises(PydanticValidationError):
            ContactTagCreateSchema(name="Bad", color=-1)


class TestProtectedCountryDelete(TestCase):
    """`Contact.country` is `PROTECT`, so a country a contact points at cannot go.

    The exposure runs the other way round from the rest of this file: what the
    relation protects is the `Country`, not the `Contact`. `CountryService` is
    deliberately read-only -- countries come from the system fixture -- so no
    registered service can delete one, and the delete surface has to be composed
    here. `ServiceRegistry` keys one service per model and raises on a second one,
    hence the swap: this service stands in for `CountryService` for the lifetime of
    the class only.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._registered = ServiceRegistry._by_model.pop(Country, None)

        class CountryDeleteService(DeleteMixin, ServiceBase[Country]):
            pass

        cls.service_class = CountryDeleteService

    @classmethod
    def tearDownClass(cls):
        # Declaring a service registers it for the whole process.
        ServiceRegistry._by_model.pop(Country, None)
        if cls._registered is not None:
            ServiceRegistry._by_model[Country] = cls._registered
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.country = Country.objects.create(code="BE", name="Belgium")
        self.service = Environment(None).get(self.service_class)

    def test_delete_a_country_a_contact_points_at_is_refused(self):
        Contact.objects.create(last_name="Tournesol", country=self.country)

        # `Country.pk` is its ISO code.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.delete)({"code": self.country.pk})

        self.assertEqual(ctx.exception.code, "protected_error")
        self.assertIn("Contact.country", str(ctx.exception.dict()["__all__"]))
        self.assertTrue(Country.objects.filter(pk=self.country.pk).exists())

    def test_delete_an_unreferenced_country(self):
        """The control: the mapping is what refuses the delete, not the delete itself."""
        async_to_sync(self.service.delete)({"code": self.country.pk})

        self.assertFalse(Country.objects.filter(pk=self.country.pk).exists())
