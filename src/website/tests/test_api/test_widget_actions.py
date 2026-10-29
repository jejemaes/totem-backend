from django.test import Client, TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.html_widget import get_widgets
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import PAGE_SCOPES, PERMISSION_DENIED, CommonTestMixin

WIDGET_FIELDS = ["id", "title", "attribute_schema"]


class HtmlWidgetActionsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The listing the editor reads to know which blocks it can offer.

    Read-only and backed by no table: the widget kinds come from the registry,
    filled at startup from the code. Hence a route only, and no
    `*_access_rules` tests: with no model, there is no rule a role could hold.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = ["totem.websitewidget.read"]
        cls.role.rules = []
        cls.role.save()

        cls.url_widgets = "/api/v1/website/widgets/"

    # ------------------------------------------
    # List Widgets
    # ------------------------------------------

    def test_list_widgets_response(self):
        response = self.do_request("GET", self.url_widgets)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        # Ordered by id: stable across restarts, whatever the app loading order.
        self.assertEqual([widget["id"] for widget in data], sorted(widget.id for widget in get_widgets()))
        widgets = {widget.id: widget for widget in get_widgets()}
        for item in data:
            self.assert_api_format(item, widgets[item["id"]])

        self.assertEqual({item["id"]: item for item in data}["last-page"]["title"], "Last Updated Pages")

    def test_list_widgets_attribute_schema(self):
        """ The point of the route: the editor builds each widget's options form
        from the schema instead of restating it in javascript. """
        widget = {w["id"]: w for w in self.do_request("GET", self.url_widgets).json()}["last-page"]
        limit = widget["attribute_schema"]["properties"]["limit"]

        self.assertEqual(
            (limit["type"], limit["minimum"], limit["maximum"], limit["default"]),
            ("integer", 1, 10, 5),
        )
        # `extra="forbid"` reaches the editor as `additionalProperties: false`, so
        # a client can tell a typo from a real parameter before saving.
        self.assertFalse(widget["attribute_schema"]["additionalProperties"])

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitewidget.read"], 200),
            (PAGE_SCOPES, 403),
        ]
    )
    def test_list_widgets_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_widgets)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitewidget.read"], 200),
            (PAGE_SCOPES, 403),
        ]
    )
    def test_list_widgets_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_widgets, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    def test_list_widgets_unauthenticated(self):
        # Django's client directly: neither credential is sent at all.
        self.assertEqual(Client().get(self.url_widgets).status_code, 401)

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

    def assert_api_format(self, api_data, widget, fields=None):
        fields = fields or WIDGET_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], widget.id)
        if "title" in fields:
            self.assertEqual(api_data["title"], widget.title)
        if "attribute_schema" in fields:
            self.assertEqual(api_data["attribute_schema"], widget.attribute_schema.model_json_schema())

        self.assertEqual(set(fields), set(api_data))
