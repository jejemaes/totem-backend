from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from base.models import Country
from contact.models import Contact, ContactTag


class TestContactModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.country = Country.objects.create(code="BE", name="Belgium")

    def test_primary_key_is_a_ulid(self):
        contact = Contact.objects.create(last_name="Tournesol")

        self.assertEqual(len(contact.pk), 26)
        self.assertTrue(contact.pk.isalnum())

    def test_primary_keys_sort_in_creation_order(self):
        first = Contact.objects.create(last_name="First")
        second = Contact.objects.create(last_name="Second")

        # This is the whole point of a ULID over a UUID4, and what makes the
        # implicit ordering added by `queryset_order_by_fields` meaningful.
        self.assertLess(first.pk, second.pk)

    def test_queryset_update_stamps_update_date(self):
        contact = Contact.objects.create(last_name="Tournesol")
        create_date, update_date = contact.create_date, contact.update_date

        # The service layer writes updates through `queryset.update()`, which does
        # not run `pre_save()` and so would leave `auto_now` untouched.
        Contact.objects.filter(pk=contact.pk).update(city="Bruxelles")

        contact.refresh_from_db()
        self.assertGreater(contact.update_date, update_date)
        self.assertEqual(contact.create_date, create_date)

    def test_queryset_update_keeps_an_explicit_update_date(self):
        contact = Contact.objects.create(last_name="Tournesol")
        forced = contact.create_date

        Contact.objects.filter(pk=contact.pk).update(update_date=forced)

        contact.refresh_from_db()
        self.assertEqual(contact.update_date, forced)

    def test_country_is_protected(self):
        Contact.objects.create(last_name="Tournesol", country=self.country)

        with self.assertRaises(ProtectedError):
            self.country.delete()

    def test_address_fields_come_from_the_mixin(self):
        contact = Contact.objects.create(
            last_name="Tournesol",
            number="12A",
            street="Rue du Labo",
            zip="1000",
            city="Bruxelles",
            country=self.country,
        )

        contact.refresh_from_db()
        self.assertEqual(contact.number, "12A")
        self.assertEqual(contact.country, self.country)


class TestContactCompanyModel(TestCase):
    """The check constraints are the last line: the service reports the same rules
    with keyed errors, but the admin and any future writer only meet these."""

    def test_display_name_of_a_person(self):
        contact = Contact.objects.create(first_name="Tryphon", last_name="Tournesol")

        contact.refresh_from_db()
        self.assertEqual(contact.display_name, "Tryphon Tournesol")

    def test_display_name_of_a_person_without_first_name(self):
        contact = Contact.objects.create(last_name="Tournesol")

        contact.refresh_from_db()
        # No leading space: `Trim`.
        self.assertEqual(contact.display_name, "Tournesol")

    def test_display_name_of_a_company(self):
        company = Contact.objects.create(is_company=True, name="Moulinsart SA")

        company.refresh_from_db()
        self.assertEqual(company.display_name, "Moulinsart SA")

    def test_display_name_follows_a_queryset_update(self):
        contact = Contact.objects.create(last_name="Tournesol")

        # The write path of the services: a generated column needs no `save()`.
        Contact.objects.filter(pk=contact.pk).update(first_name="Tryphon")

        contact.refresh_from_db()
        self.assertEqual(contact.display_name, "Tryphon Tournesol")

    def test_person_needs_a_last_name(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(first_name="Tryphon")

    def test_company_needs_a_name(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(is_company=True, vat="BE0123456789")

    def test_person_cannot_have_company_fields(self):
        for values in ({"name": "Moulinsart SA"}, {"vat": "BE0123456789"}):
            with self.subTest(values), self.assertRaises(IntegrityError), transaction.atomic():
                Contact.objects.create(last_name="Tournesol", **values)

    def test_company_cannot_have_person_fields(self):
        for values in ({"first_name": "Tryphon"}, {"last_name": "Tournesol"}):
            with self.subTest(values), self.assertRaises(IntegrityError), transaction.atomic():
                Contact.objects.create(is_company=True, name="Moulinsart SA", **values)

    def test_company_cannot_have_a_parent(self):
        parent = Contact.objects.create(is_company=True, name="Moulinsart SA")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(is_company=True, name="Labo SPRL", parent=parent)

    def test_person_cannot_be_its_own_parent(self):
        contact = Contact.objects.create(last_name="Tournesol")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.filter(pk=contact.pk).update(parent=contact)

    def test_vat_is_unique_case_insensitive(self):
        Contact.objects.create(is_company=True, name="Moulinsart SA", vat="BE0123456789")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Contact.objects.create(is_company=True, name="Moulinsart Bis", vat="be0123456789")

    def test_deleting_a_company_keeps_its_persons(self):
        company = Contact.objects.create(is_company=True, name="Moulinsart SA")
        person = Contact.objects.create(last_name="Tournesol", parent=company)

        company.delete()

        person.refresh_from_db()
        self.assertIsNone(person.parent_id)


class TestContactTagModel(TestCase):

    def test_name_is_unique(self):
        ContactTag.objects.create(name="VIP")

        with self.assertRaises(IntegrityError), transaction.atomic():
            ContactTag.objects.create(name="VIP")

    def test_color_upper_bound(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContactTag.objects.create(name="Bad", color=16)

    def test_color_bounds_are_inclusive(self):
        ContactTag.objects.create(name="Low", color=0)
        ContactTag.objects.create(name="High", color=15)

        self.assertEqual(ContactTag.objects.count(), 2)
