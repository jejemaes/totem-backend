from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Website
from website.theme import DEFAULT_THEME_ID

from .common import PERMISSION_DENIED, WEBSITE_ID, WEBSITE_SCOPES, CommonTestMixin

# A well-formed but absent ULID: the schema types a relation with the target's
# primary key type, so a malformed one would be refused before the service runs.
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


class WebsiteAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The site's own settings, through the generated `/{id}/` routes.

    A singleton: retrieve and update only, composed by hand rather than through
    `ModelController` (see `WebsiteController`). `/current/` is the route a
    client actually uses, tested in `test_website_actions.py`; `/{id}/` is tested
    because it exists, not because anything calls it.

    No `*_access_rules` tests: no `BaseRule` is registered for `Website`, and that
    is load-bearing -- the public render path reads the row with no role, and the
    first rule would filter it to nothing (see `website.security`).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = WEBSITE_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/websites/"
        cls.url_detail = f"/api/v1/website/websites/{WEBSITE_ID}/"
        cls.payload_update = {
            "name": "Gondor",
            "headline": "The White City",
            "meta_authors": "The Stewards",
            "meta_description": "Minas Tirith and its seven levels",
            "footer": "<p>The Citadel</p>",
        }

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        # Both relations are set, so serializing them is what forces them to be
        # resolved: this covers the relational part of the payload.
        self.assert_api_format(response.json(), self.website)

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{UNKNOWN_ID}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.website.read"], 200),
            (["totem.website.update"], 403),
            (["totem.websitepage.read"], 403),
        ]
    )
    def test_retrieve_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_detail)

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
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            ({"headline": None}, 422, "headline"),
            ({"meta_authors": None}, 200, None),
            ({"meta_description": None}, 200, None),
            ({"footer": None}, 200, None),
            ({"homepage": None}, 200, None),
            ({"menu": None}, 200, None),
            ({"homepage": UNKNOWN_ID}, 422, "homepage"),
            ({"menu": UNKNOWN_ID}, 422, "menu"),
            ({"footer": '<t-widget name="nope"></t-widget>'}, 422, "footer"),
            ({"theme": None}, 422, "theme"),
            ({"theme": "no-such-theme"}, 422, "theme"),
            ({"theme": DEFAULT_THEME_ID}, 200, None),
            ({"theme_options": {"nope": 1}}, 422, "theme_options"),
            ({"theme_options": {}}, 200, None),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        """ `name` and `headline` are NOT NULL, everything else here is nullable.

        Each refusal is asserted on the field it names, not just on the status:
        three quite different mechanisms produce these 422s. `null` on a non-null
        column is refused by the null check of the schemas and services; the
        relation rows are the scoped resolution through `browse`; the `footer`
        row is `HtmlField(allow_widget=True)` refusing a marker that names no
        registered widget.
        """
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        obj = Website.objects.get(id=WEBSITE_ID)
        self.assertEqual(obj.name, "Gondor")
        # The relations were not in the payload and must survive it, still
        # expanded in the response.
        self.assert_api_format(response.json(), obj)

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{UNKNOWN_ID}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Website.objects.get(pk=WEBSITE_ID).name, "Middle-earth")

    @parameterized.expand(
        [
            ([], 403),
            (["totem.website.update"], 200),
            (["totem.website.read"], 403),
            (["totem.websitepage.update"], 403),
        ]
    )
    def test_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

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
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Operations that must NOT exist
    # ------------------------------------------

    def test_delete_is_not_allowed(self):
        """ Regression guard for the `ModelController` trap.

        `DeleteModelControllerMixin.add_routes_to` is gated on `if cls.model:`
        alone, so inheriting `ModelController` would register `DELETE /{id}/` --
        and a key absent from `permission_map` requires no scope, leaving the
        site's settings deletable by any authenticated token. Composing the
        mixins by hand is what prevents it, and this is what would notice a
        revert.

        405 and not 404: `/{id}/` does exist, for GET and PATCH.
        """
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Website.objects.filter(pk=WEBSITE_ID).exists())

    @parameterized.expand([("GET",), ("POST",)])
    def test_the_collection_path_has_no_route(self, method):
        """ No list and no create, so the collection path is unrouted.

        404 rather than the 405 `/{id}/` answers, and the difference is the
        point: nothing is registered here, so django never reaches a view to
        reject the method. Asserting 405 would be asserting a route exists.
        """
        response = self.do_request(method, self.url, data=self.payload_update)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Website.objects.count(), 1)

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
            # A JSON column, so the payload is the stored value verbatim -- the
            # converter maps it to `AnyObject` rather than coercing it.
            self.assertEqual(api_data["theme_options"], obj.theme_options)
        # Display-name objects rather than bare pks: the editor needs a label to
        # show. The nested shape also proves the relation was resolved before
        # serialization -- an unresolved one raises `SynchronousOnlyOperation`.
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
