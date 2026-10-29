from django.test import Client, TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.theme import DEFAULT_THEME_ID, LAYOUT_DEFAULT, LAYOUTS, get_themes

from .common import PAGE_SCOPES, PERMISSION_DENIED, CommonTestMixin

THEME_FIELDS = ["id", "title", "layouts", "option_schema"]


class ThemeActionsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The catalogue an editor reads to offer a theme and a layout.

    Read-only and backed by no table: the themes come from the registry, filled
    at startup from the code, and the layout vocabulary is a module constant.
    Hence routes only, and no `*_access_rules` tests: with no model, there is no
    rule a role could hold to narrow them.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = ["totem.websitetheme.read"]
        cls.role.rules = []
        cls.role.save()

        cls.url_themes = "/api/v1/website/themes/"
        cls.url_layouts = "/api/v1/website/themes/layouts/"

    # ------------------------------------------
    # List Themes
    # ------------------------------------------

    def test_list_themes_response(self):
        response = self.do_request("GET", self.url_themes)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        # Ordered by id: stable whatever the order the registry was filled in.
        self.assertEqual([theme["id"] for theme in data], sorted(theme.id for theme in get_themes()))
        themes = {theme.id: theme for theme in get_themes()}
        for item in data:
            self.assert_api_format(item, themes[item["id"]])

        default = {item["id"]: item for item in data}[DEFAULT_THEME_ID]
        self.assertEqual(default["title"], "Superhero")
        self.assertIn(LAYOUT_DEFAULT, default["layouts"])

    def test_list_themes_option_schema(self):
        """ The point of the route: the editor builds the settings form from the
        schema instead of restating each theme's options in javascript. """
        for theme in self.do_request("GET", self.url_themes).json():
            with self.subTest(theme=theme["id"]):
                self.assertIn("properties", theme["option_schema"])
                # `extra="forbid"` reaches the editor as `additionalProperties:
                # false`, so a client can tell a typo from a real option.
                self.assertFalse(theme["option_schema"]["additionalProperties"])
                # Asserted on the wire because it is what makes the read path
                # total: the metaclass refuses an option without a default, so
                # `resolve_options` can always fall back to it.
                for name, spec in theme["option_schema"].get("properties", {}).items():
                    with self.subTest(option=name):
                        self.assertIn("default", spec)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitetheme.read"], 200),
            (PAGE_SCOPES, 403),
        ]
    )
    def test_list_themes_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_themes)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitetheme.read"], 200),
            (PAGE_SCOPES, 403),
        ]
    )
    def test_list_themes_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_themes, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    def test_list_themes_unauthenticated(self):
        # Django's client directly: neither credential is sent at all.
        self.assertEqual(Client().get(self.url_themes).status_code, 401)

    # ------------------------------------------
    # List Layouts
    # ------------------------------------------

    def test_list_layouts_response(self):
        """ The labels belong to the vocabulary, not to any one theme. Without
        this route an editor would restate them in javascript. """
        response = self.do_request("GET", self.url_layouts)

        self.assertEqual(response.status_code, 200)
        self.assertEqual({layout["id"]: layout["title"] for layout in response.json()}, LAYOUTS)
        for layout in response.json():
            self.assertEqual(set(layout), {"id", "title"})

    def test_list_layouts_covers_every_theme(self):
        # Enforced by the metaclass; asserted here across the wire: a theme only
        # implements layouts of the vocabulary.
        vocabulary = {layout["id"] for layout in self.do_request("GET", self.url_layouts).json()}

        for theme in self.do_request("GET", self.url_themes).json():
            with self.subTest(theme=theme["id"]):
                self.assertLessEqual(set(theme["layouts"]), vocabulary)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitetheme.read"], 200),
            (PAGE_SCOPES, 403),
        ]
    )
    def test_list_layouts_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_layouts)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitetheme.read"], 200),
            (PAGE_SCOPES, 403),
        ]
    )
    def test_list_layouts_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_layouts, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    def test_list_layouts_unauthenticated(self):
        self.assertEqual(Client().get(self.url_layouts).status_code, 401)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, theme, fields=None):
        fields = fields or THEME_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], theme.id)
        if "title" in fields:
            self.assertEqual(api_data["title"], theme.title)
        if "layouts" in fields:
            self.assertEqual(api_data["layouts"], sorted(theme.layouts))
        if "option_schema" in fields:
            self.assertEqual(api_data["option_schema"], theme.option_schema.model_json_schema())

        self.assertEqual(set(fields), set(api_data))
