"""The theme choosing the template, and degrading when it cannot.

Assertions are on `response.template_name`, never `assertTemplateUsed`. The
latter patches `django.template.base.Template._render`, which no jinja render
goes through, so `response.templates` stays empty and the assertion silently
tests nothing -- a trap for the whole project, since every website template is
jinja. `response.template_name` is the candidate list `get_template_names()`
returned, so it also shows *which rung* of the fallback answered.
"""

from django.test import Client, TestCase

from website.models import Page, Website
from website.theme import DEFAULT_THEME_ID
from website.views import PageView

from .common import WebsiteViewTestMixin


class TestThemeRendering(WebsiteViewTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.page = self.build_page(slug="tresor", layout="narrow")
        self.menu = self.build_menu_tree(page=self.page)
        self.website = self.build_website(menu=self.menu)

    def _url(self, slug="tresor"):
        return f"/page/{slug}/"

    # ------------------------------------------
    # Template selection
    # ------------------------------------------

    def test_the_page_layout_selects_the_template(self):
        response = self.get_unrendered_response(PageView, self._url(), slug="tresor")

        self.assertEqual(
            response.template_name[0],
            "website/themes/default/layouts/narrow.html",
        )

    def test_the_rendered_markup_is_the_one_of_that_layout(self):
        response = Client().get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "t-narrow")
        self.assertContains(response, 't-layout--narrow')

    def test_a_layout_the_theme_does_not_implement_falls_back(self):
        """Rung two, and the guarantee that switching theme cannot break a page.

        The default theme implements every layout, so the page is given one that
        is not in the vocabulary at all -- which reaches the same rung, since
        resolution is by filesystem and rung one simply misses.
        """
        Page.objects.filter(pk=self.page.pk).update(layout="no-such-layout")

        response = Client().get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.template_name,
            [
                "website/themes/default/layouts/no-such-layout.html",
                "website/themes/default/layouts/full-width.html",
            ],
        )

    # ------------------------------------------
    # Degradation
    # ------------------------------------------

    def test_an_unknown_theme_falls_back_to_the_default_and_logs(self):
        """A theme deleted from the code while a row still points at it."""
        Website.objects.filter(pk=self.website.pk).update(theme="deleted-theme")

        with self.assertLogs("website.views.mixins", level="WARNING"):
            response = Client().get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.template_name[0],
            "website/themes/default/layouts/narrow.html",
        )

    def test_the_site_renders_without_a_website_row(self):
        """A freshly provisioned database: `/` must still answer."""
        Website.objects.all().delete()

        response = Client().get("/")

        self.assertEqual(response.status_code, 200)

    # ------------------------------------------
    # Options -> CSS
    # ------------------------------------------

    def test_a_stored_option_reaches_the_page_as_a_custom_property(self):
        Website.objects.filter(pk=self.website.pk).update(
            theme_options={"color_primary": "#c0392b"}
        )

        response = Client().get(self._url())

        self.assertContains(response, "--t-color-primary: #c0392b;")

    def test_no_options_means_no_style_block(self):
        """The stylesheet's own `:root` stands, so nothing has to be emitted."""
        response = Client().get(self._url())

        self.assertNotContains(response, "--t-color-primary")

    def test_options_left_over_from_another_theme_are_ignored(self):
        Website.objects.filter(pk=self.website.pk).update(
            theme_options={"some_other_theme_option": "x"}
        )

        response = Client().get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "some_other_theme_option")

    # ------------------------------------------
    # What the chrome carries
    # ------------------------------------------

    def test_the_title_names_the_page_and_the_site(self):
        response = Client().get(self._url())

        self.assertContains(
            response, "<title>Le Trésor de Rackham · Moulinsart</title>"
        )

    def test_a_new_window_menu_item_opens_in_a_tab_and_is_safe(self):
        """The regression pair the inverted condition never had.

        `{% if not node.data.new_window %}` used to emit `target="_blank"` for
        every item that was *not* marked, and nothing at all for the ones that
        were. `rel="noopener"` was missing either way, which hands the opened
        page a live `window.opener`.
        """
        response = Client().get(self._url())

        self.assertContains(
            response,
            '<a class="nav-link" href="https://example.test" target="_blank" rel="noopener">Extern</a>',
            html=False,
        )

    def test_an_ordinary_menu_item_stays_in_the_tab(self):
        response = Client().get(self._url())
        html = response.content.decode()

        home_link = [line for line in html.splitlines() if ">Home<" in line][0]
        self.assertNotIn("target=", home_link)

    def test_the_theme_assets_are_loaded(self):
        response = Client().get(self._url())

        self.assertContains(response, "bootswatch@5.3.8/dist/superhero")
        self.assertContains(response, "/static/website/themes/default/theme.css")

    def test_resolving_the_theme_costs_no_query(self):
        """It reads the already-loaded row and the in-process registry.

        The assertion that pins the design: the theme must not become something
        the render path pays for.
        """
        with self.assertNumQueries(4):
            # page, website, menu root, menu subtree -- and nothing for the theme.
            Client().get(self._url())
