from django.test import TestCase

from website.models import Page
from website.theme import LAYOUT_DEFAULT


class TestPageModel(TestCase):
    """The historical write path, which the admin still uses."""

    def test_save_stamps_the_publication_date_on_insert(self):
        # Creating something already published is a publication too. Without the
        # insert branch in `WebsitePublishedMixin.save()`, the admin left this
        # empty while the service stamped it -- two paths disagreeing about the
        # same field.
        page = Page.objects.create(
            title="Page", slug="page", content="<p>x</p>", is_published=True
        )

        self.assertIsNotNone(page.date_published)

    def test_save_leaves_the_publication_date_unset_when_not_published(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")

        self.assertIsNone(page.date_published)

    def test_save_stamps_the_publication_date_when_publishing(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")

        page.is_published = True
        page.save(update_fields=["is_published"])

        page.refresh_from_db()
        self.assertIsNotNone(page.date_published)

    def test_queryset_update_moves_the_update_date(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")
        before = page.update_date

        Page.objects.filter(pk=page.pk).update(title="Renamed")

        page.refresh_from_db()
        self.assertGreater(page.update_date, before)


class TestPagePrimaryKey(TestCase):

    def test_primary_key_is_a_ulid(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")

        self.assertEqual(len(page.pk), 26)
        self.assertTrue(page.pk.isalnum())

    def test_primary_keys_sort_in_creation_order(self):
        first = Page.objects.create(title="First", slug="first", content="<p>x</p>")
        second = Page.objects.create(title="Second", slug="second", content="<p>x</p>")

        # This is the whole point of a ULID over a UUID4, and what makes the
        # implicit ordering added by `queryset_order_by_fields` meaningful.
        self.assertLess(first.pk, second.pk)

    def test_a_fresh_page_gets_the_default_layout(self):
        page = Page.objects.create(title="Le Hike", slug="hike", content="<p>x</p>")

        self.assertEqual(page.layout, LAYOUT_DEFAULT)

    def test_updating_the_layout_still_stamps_the_update_date(self):
        """Guards the interaction between the new field and `PageQuerySet.update`."""
        page = Page.objects.create(title="Le Hike", slug="hike", content="<p>x</p>")
        before = page.update_date

        Page.objects.filter(pk=page.pk).update(layout="narrow")

        page.refresh_from_db()
        self.assertEqual(page.layout, "narrow")
        self.assertGreater(page.update_date, before)
