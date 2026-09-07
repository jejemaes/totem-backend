from django.test import TestCase

from website.models import Page


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
