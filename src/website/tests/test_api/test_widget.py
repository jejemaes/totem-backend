import json

from django.test import Client, TestCase

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin


class HtmlWidgetAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """The listing the editor reads to know which blocks it can offer.

    Read-only and backed by no table: the widget kinds come from the registry,
    filled at startup from the code.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_access_token_frodon.scope = "totem.websitewidget.read"
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/website/widgets/"

    @property
    def token(self):
        return self.user_access_token_frodon.token

    def _list(self):
        response = self.do_api_request(self.url, "GET", self.token)
        self.assertEqual(response.status_code, 200)
        return json.loads(response.content)

    def test_list_returns_the_registered_widgets(self):
        widgets = {widget["id"]: widget for widget in self._list()}

        self.assertIn("last-page", widgets)
        self.assertEqual(widgets["last-page"]["title"], "Last Updated Pages")

    def test_a_widget_carries_the_json_schema_of_its_parameters(self):
        # This is the point of the route: the editor builds each widget's
        # options form from the schema instead of restating it in javascript.
        widget = {w["id"]: w for w in self._list()}["last-page"]
        properties = widget["attribute_schema"]["properties"]

        self.assertEqual(properties["limit"]["type"], "integer")
        self.assertEqual(properties["limit"]["minimum"], 1)
        self.assertEqual(properties["limit"]["maximum"], 10)
        self.assertEqual(properties["limit"]["default"], 5)

    def test_the_schema_refuses_unknown_parameters(self):
        # `extra="forbid"` reaches the editor as `additionalProperties: false`,
        # so a client can tell a typo from a real parameter before saving.
        widget = {w["id"]: w for w in self._list()}["last-page"]

        self.assertFalse(widget["attribute_schema"]["additionalProperties"])

    def test_the_listing_is_ordered_by_id(self):
        # Stable across restarts: the registry is a dict keyed by id, whose
        # insertion order follows app loading.
        ids = [widget["id"] for widget in self._list()]

        self.assertEqual(ids, sorted(ids))

    def test_list_without_the_scope_is_403(self):
        self.user_access_token_frodon.scope = "totem.websitepage.read"
        self.user_access_token_frodon.save()

        response = self.do_api_request(self.url, "GET", self.token)

        self.assertEqual(response.status_code, 403)

    def test_list_without_a_token_is_401(self):
        # Django's client directly: `do_api_request` builds the header by
        # concatenating the token, so it cannot express "no token at all".
        response = Client().get(self.url)

        self.assertEqual(response.status_code, 401)
