import json

from django.test import Client, TestCase

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.theme import DEFAULT_THEME_ID, LAYOUT_DEFAULT, LAYOUTS


class ThemeAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """The catalogue an editor reads to offer a theme and a layout.

    Read-only and backed by no table: the themes come from the registry, filled
    at startup from the code, and the layout vocabulary is a module constant.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_access_token_frodon.scope = "totem.websitetheme.read"
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/website/themes/"
        cls.url_layouts = "/api/v1/website/themes/layouts/"

    @property
    def token(self):
        return self.user_access_token_frodon.token

    def _list(self, url=None):
        response = self.do_api_request(url or self.url, "GET", self.token)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    # ------------------------------------------
    # Theme listing
    # ------------------------------------------

    def test_list_returns_the_registered_themes(self):
        themes = {theme["id"]: theme for theme in self._list()}

        self.assertIn(DEFAULT_THEME_ID, themes)
        self.assertEqual(themes[DEFAULT_THEME_ID]["title"], "Superhero")

    def test_a_theme_carries_the_json_schema_of_its_options(self):
        # The point of the route: the editor builds the settings form from the
        # schema instead of restating each theme's options in javascript.
        theme = {t["id"]: t for t in self._list()}[DEFAULT_THEME_ID]

        self.assertIn("properties", theme["option_schema"])

    def test_every_option_declares_a_default(self):
        """Asserted on the wire, because it is what makes the read path total.

        The metaclass refuses an option without a default so that
        `resolve_options` can always fall back to `option_schema()`. Pinning it
        here means the guarantee cannot regress silently for a theme added
        later.
        """
        for theme in self._list():
            properties = theme["option_schema"].get("properties", {})
            for name, spec in properties.items():
                with self.subTest(theme=theme["id"], option=name):
                    self.assertIn("default", spec)

    def test_the_schema_refuses_unknown_options(self):
        # `extra="forbid"` reaches the editor as `additionalProperties: false`,
        # so a client can tell a typo from a real option before saving.
        for theme in self._list():
            with self.subTest(theme=theme["id"]):
                self.assertFalse(theme["option_schema"]["additionalProperties"])

    def test_a_theme_lists_the_layouts_it_implements(self):
        theme = {t["id"]: t for t in self._list()}[DEFAULT_THEME_ID]

        self.assertIn(LAYOUT_DEFAULT, theme["layouts"])
        self.assertEqual(theme["layouts"], sorted(theme["layouts"]))

    def test_the_listing_is_ordered_by_id(self):
        ids = [theme["id"] for theme in self._list()]

        self.assertEqual(ids, sorted(ids))

    # ------------------------------------------
    # Layout vocabulary
    # ------------------------------------------

    def test_the_layout_route_returns_the_vocabulary_with_its_labels(self):
        """The labels belong to the vocabulary, not to any one theme.

        Without this route an editor would restate them in javascript -- the
        exact duplication `option_schema` exists to avoid.
        """
        layouts = {layout["id"]: layout["title"] for layout in self._list(self.url_layouts)}

        self.assertEqual(layouts, LAYOUTS)

    def test_every_theme_implements_a_subset_of_the_vocabulary(self):
        """Enforced by the metaclass; asserted here across the wire."""
        vocabulary = {layout["id"] for layout in self._list(self.url_layouts)}

        for theme in self._list():
            with self.subTest(theme=theme["id"]):
                self.assertLessEqual(set(theme["layouts"]), vocabulary)

    # ------------------------------------------
    # Permissions
    # ------------------------------------------

    def test_list_without_the_scope_is_403(self):
        self.user_access_token_frodon.scope = "totem.websitepage.read"
        self.user_access_token_frodon.save()

        for url in (self.url, self.url_layouts):
            with self.subTest(url=url):
                response = self.do_api_request(url, "GET", self.token)

                self.assertEqual(response.status_code, 403)

    def test_list_without_a_token_is_401(self):
        # Django's client directly: `do_api_request` builds the header by
        # concatenating the token, so it cannot express "no token at all".
        for url in (self.url, self.url_layouts):
            with self.subTest(url=url):
                self.assertEqual(Client().get(url).status_code, 401)
