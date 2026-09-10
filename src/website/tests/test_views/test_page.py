from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from website.models import Page, Website
from website.services import PageService, WebsiteService
from website.views import PageView

from .common import WebsiteViewTestMixin


class TestPageView(WebsiteViewTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.page = self.build_page(slug="tresor")
        self.menu = self.build_menu_tree(page=self.page)
        self.website = self.build_website(menu=self.menu)

    def _url(self, slug="tresor"):
        return reverse("page", kwargs={"slug": slug})

    def test_a_published_page_renders(self):
        response = Client().get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Le Trésor de Rackham")
        self.assertContains(response, "Mille sabords")

    def test_an_unpublished_page_is_not_found(self):
        # Publication is a filter the view asks the service for, not an access
        # rule: a visitor is anonymous and roleless, so a `BaseRule` would
        # filter nothing at all and every draft would be public.
        self.build_page(slug="brouillon", published=False)

        response = Client().get(self._url("brouillon"))

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_slug_is_not_found(self):
        response = Client().get(self._url("nowhere"))

        self.assertEqual(response.status_code, 404)

    def test_the_page_is_in_the_render_context(self):
        response = self.get_unrendered_response(PageView, self._url(), slug="tresor")

        self.assertEqual(response.context_data["page"].pk, self.page.pk)
        self.assertEqual(response.context_data["object"].pk, self.page.pk)

    def test_the_website_is_read_through_its_service(self):
        """Pins the last of the ORM out of this module.

        `get_website` used to be `await Website.objects.afirst()`, the one place
        the website views reached the database directly.
        """
        with patch.object(
            WebsiteService, "read_current", wraps=WebsiteService.read_current,
            autospec=True,
        ) as read_current:
            Client().get(self._url())

        self.assertTrue(read_current.called)
        # No `fields=`: it would become an `only()`, and the layout reads
        # `name`/`headline` while the context mixin reads `menu_id`,
        # `homepage_id` and `footer`. See `WebsiteService.read_current`.
        self.assertIsNone(read_current.call_args.kwargs.get("fields"))

    def test_the_public_path_costs_no_extra_query(self):
        """Routing the website read through a service must stay free.

        `apply_access_rules` returns the queryset untouched for a model with no
        rule registered, and `Environment.get_access_roles()` issues no query
        while `user is None` -- which is every request here. Pinning the count
        is what would catch a `BaseRule` being declared for `Website`, or the
        access machinery starting to query for anonymous callers.
        """
        with self.assertNumQueries(4):
            # The page, the website, the menu root's own `parent_path`, and the
            # subtree -- and nothing at all for the acting user's roles. The
            # third one is `read_tree` resolving the root before it can filter on
            # a prefix, which is what lets `Website.menu` point at an inner item.
            Client().get(self._url())

    def test_the_page_is_read_through_its_service(self):
        # Pins that the view holds no queryset of its own.
        with patch.object(
            PageService, "read_published", wraps=PageService.read_published,
            autospec=True,
        ) as read_published:
            Client().get(self._url())

        self.assertTrue(read_published.called)
        self.assertEqual(
            read_published.call_args.kwargs["filters"], {"slug": "tresor"}
        )

    def test_render_makes_no_query(self):
        Page.objects.filter(pk=self.page.pk).update(
            content=f"<div><p>x</p>{self.marker(attrs={'limit': 3})}</div>"
        )
        Website.objects.filter(pk=self.website.pk).update(
            footer=f"<div>{self.marker()}</div>"
        )

        response = self.get_unrendered_response(PageView, self._url(), slug="tresor")

        with self.assertNumQueries(0):
            response.render()
        self.assertEqual(response.status_code, 200)
