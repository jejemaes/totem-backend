from django.test import Client, TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Website
from website.theme import DEFAULT_THEME_ID

from .common import MENU_ID1, PAGE_ID1, PERMISSION_DENIED, WEBSITE_ID, WEBSITE_SCOPES, CommonTestMixin

UNKNOWN_ID = "01M209K5BNS12QRPHXFWVJ0000"

WEBSITE_FIELDS = [
    "id",
    "name",
    "headline",
    "meta_authors",
    "meta_description",
    "menu",
    "homepage",
    "footer",
    "side_bar_content",
    "theme",
    "theme_options",
]


class WebsiteActionsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `/website/websites/current/`: the route a client uses, since the row is a
    singleton provisioned under a fixed pk and nobody has an id to send.

    No `*_access_rules` tests: no `BaseRule` is registered for `Website`, and that
    is load-bearing (see `website.security`).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = WEBSITE_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url_current = "/api/v1/website/websites/current/"
        cls.payload_update = {
            "name": "Gondor",
            "headline": "The White City",
            "meta_authors": "The Stewards",
            "meta_description": "Minas Tirith and its seven levels",
            "footer": "<p>The Citadel</p>",
        }

    # ------------------------------------------
    # Current Read
    # ------------------------------------------

    def test_current_read_response(self):
        response = self.do_request("GET", self.url_current)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["menu"]["id"], MENU_ID1)
        self.assertEqual(response.json()["homepage"]["id"], PAGE_ID1)
        self.assert_api_format(response.json(), self.website)

    def test_current_read_response_without_relations(self):
        """ A freshly provisioned site has no homepage and no main menu yet.

        The state `HomePageView` degrades on, so the payload has to express it:
        `null`, and the keys still present -- an editor offering "pick a
        homepage" needs to see the field, not have it disappear.
        """
        Website.objects.filter(pk=WEBSITE_ID).update(menu=None, homepage=None)

        response = self.do_request("GET", self.url_current)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["menu"])
        self.assertIsNone(response.json()["homepage"])
        self.assert_api_format(response.json(), Website.objects.get(pk=WEBSITE_ID))

    def test_current_read_wins_the_path_match_against_the_id_route(self):
        """ Load-bearing registration order, so it gets its own test.

        `current_read` is in `cls.__dict__` from the class body, while `retrieve`
        is only put there later by `method_to_route_function`, so `/current/` is
        registered first. If that ever inverted, this request would be matched by
        `retrieve` with `id="current"` and answer 404.
        """
        response = self.do_request("GET", self.url_current)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], WEBSITE_ID)

    def test_current_read_not_found(self):
        # An unpopulated database: no singleton yet.
        Website.objects.all().delete()

        response = self.do_request("GET", self.url_current)

        self.assertEqual(response.status_code, 404)

    def test_current_read_without_credentials(self):
        # Django's client directly: `do_request` always sends a credential.
        response = Client().get(self.url_current)

        self.assertEqual(response.status_code, 401)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.website.read"], 200),
            (["totem.website.update"], 403),
            (["totem.websitepage.read"], 403),
        ]
    )
    def test_current_read_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_current)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.website.read"], 200),
            (["totem.website.update"], 403),
            (["totem.websitepage.read"], 403),
        ]
    )
    def test_current_read_apikey_access_rights(self, permissions, status_code):
        # Unlike `/users/me/`, `/current/` needs no user: a key holding the scope
        # reads the site.
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_current, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Current Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 200, None),
            ({"name": None}, 422, "name"),
            ({"headline": None}, 422, "headline"),
            ({"meta_authors": None}, 200, None),
            ({"footer": None}, 200, None),
            ({"homepage": None}, 200, None),
            ({"menu": None}, 200, None),
            ({"homepage": UNKNOWN_ID}, 422, "homepage"),
            ({"menu": UNKNOWN_ID}, 422, "menu"),
            ({"footer": '<t-widget name="nope"></t-widget>'}, 422, "footer"),
            ({"theme": "no-such-theme"}, 422, "theme"),
            ({"theme": DEFAULT_THEME_ID}, 200, None),
            ({"theme_options": {"nope": 1}}, 422, "theme_options"),
        ]
    )
    def test_current_update_request(self, extra_body, status_code, error_field):
        response = self.do_request("PATCH", self.url_current, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_current_update_response(self):
        response = self.do_request("PATCH", self.url_current, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        obj = Website.objects.get(id=WEBSITE_ID)
        self.assertEqual(obj.name, "Gondor")
        self.assertEqual(obj.footer, "<p>The Citadel</p>")
        self.assert_api_format(response.json(), obj)

    def test_current_update_switching_theme_clears_the_stored_options(self):
        """ The values are keyed by one theme's `option_schema`.

        Nothing maps them onto another theme's, so the switch drops them rather
        than carrying dead state forward.
        """
        Website.objects.filter(pk=WEBSITE_ID).update(theme_options={"stale": 1})

        response = self.do_request("PATCH", self.url_current, data={"theme": DEFAULT_THEME_ID})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["theme_options"], {})
        self.assertEqual(Website.objects.get(pk=WEBSITE_ID).theme_options, {})

    def test_current_update_not_found(self):
        # An unpopulated database: nothing to update, and nothing created.
        Website.objects.all().delete()

        response = self.do_request("PATCH", self.url_current, data=self.payload_update)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Website.objects.count(), 0)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.website.update"], 200),
            (["totem.website.read"], 403),
            (["totem.websitepage.update"], 403),
        ]
    )
    def test_current_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_current, data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.website.update"], 200),
            (["totem.website.read"], 403),
            (["totem.websitepage.update"], 403),
        ]
    )
    def test_current_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_current, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

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

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or WEBSITE_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "headline" in fields:
            self.assertEqual(api_data["headline"], obj.headline)
        if "meta_authors" in fields:
            self.assertEqual(api_data["meta_authors"], obj.meta_authors)
        if "meta_description" in fields:
            self.assertEqual(api_data["meta_description"], obj.meta_description)
        if "footer" in fields:
            self.assertEqual(api_data["footer"], obj.footer)
        if "side_bar_content" in fields:
            self.assertEqual(api_data["side_bar_content"], obj.side_bar_content)
        if "theme" in fields:
            self.assertEqual(api_data["theme"], obj.theme)
        if "theme_options" in fields:
            self.assertEqual(api_data["theme_options"], obj.theme_options)
        if "menu" in fields:
            if obj.menu_id:
                self.assertEqual(api_data["menu"], {"id": obj.menu.pk, "name": obj.menu.name})
            else:
                self.assertIsNone(api_data["menu"])
        if "homepage" in fields:
            if obj.homepage_id:
                self.assertEqual(
                    api_data["homepage"],
                    {"id": obj.homepage.pk, "title": obj.homepage.title, "slug": obj.homepage.slug},
                )
            else:
                self.assertIsNone(api_data["homepage"])

        self.assertEqual(set(fields), set(api_data))
