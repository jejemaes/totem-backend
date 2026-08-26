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
