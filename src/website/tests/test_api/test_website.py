import json

from django.test import Client, TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.models import Menu, Page, Website

ALL_SCOPES = "totem.website.read totem.website.update"


class WebsiteAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """The site's own settings, which had no route at all before this.

    Addressed through `/current/` rather than by id: the row is a singleton
    provisioned under a fixed pk, so a client has no id to send.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.page = Page.objects.create(
            title="Le Hike", slug="hike", content="<p>Mille sabords</p>",
            is_published=True,
        )
        cls.menu = Menu.objects.create(name="Main")
        cls.website = Website.objects.create(
            name="Le Trésor",
            headline="Rackham le Rouge",
            footer="<p>Mille sabords</p>",
            menu=cls.menu,
            homepage=cls.page,
        )

        cls.user_access_token_frodon.scope = ALL_SCOPES
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/website/websites/"
        cls.current_url = f"{cls.url}current/"

    @property
    def token(self):
        return self.user_access_token_frodon.token

    # ------------------------------------------
    # Read
    # ------------------------------------------

    def test_current_read_returns_the_settings(self):
        response = self.do_api_request(self.current_url, "GET", self.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["id"], self.website.pk)
        self.assertEqual(data["name"], "Le Trésor")
        self.assertEqual(data["headline"], "Rackham le Rouge")
        self.assertEqual(data["footer"], "<p>Mille sabords</p>")

    def test_current_read_expands_the_relations(self):
        """Display-name objects, not bare pks: the editor needs a label to show.

        Also the guard that the response is fully loaded -- ninja serializes
        outside any `sync_to_async`, so an unresolved relation here would raise
        `SynchronousOnlyOperation` rather than return a pk.
        """
        data = self.do_api_request(self.current_url, "GET", self.token).json()

        self.assertEqual(data["homepage"]["title"], "Le Hike")
        self.assertEqual(data["homepage"]["slug"], "hike")
        self.assertEqual(data["menu"]["name"], "Main")

    def test_current_wins_the_path_match_against_the_id_route(self):
        """Load-bearing registration order, so it gets its own test.

        `BaseController.add_routes_to` sorts by `list(cls.__dict__).index(name)`.
        `current_read` is in `__dict__` from the class body while `retrieve` is
        only put there later by `method_to_route_function`, so `/current/` is
        registered first. If that ever inverted, this request would be matched by
        `retrieve` with `id="current"` and answer 404 instead.
        """
        response = self.do_api_request(self.current_url, "GET", self.token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.website.pk)

    def test_retrieve_by_id_still_works(self):
        response = self.do_api_request(
            f"{self.url}{self.website.pk}/", "GET", self.token
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Le Trésor")

    def test_current_read_is_404_on_an_unpopulated_database(self):
        Website.objects.all().delete()

        response = self.do_api_request(self.current_url, "GET", self.token)

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_current_update_writes_and_echoes_the_record(self):
        body = json.dumps({"name": "Moulinsart", "footer": "<p>Tonnerre</p>"})

        response = self.do_api_request(
            self.current_url, "PATCH", self.token, data=body
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["name"], "Moulinsart")
        self.assertEqual(data["footer"], "<p>Tonnerre</p>")
        # The relations survive a partial update and are still expanded.
        self.assertEqual(data["homepage"]["title"], "Le Hike")

        self.website.refresh_from_db()
        self.assertEqual(self.website.name, "Moulinsart")

    def test_current_update_is_404_on_an_unpopulated_database(self):
        Website.objects.all().delete()
        body = json.dumps({"name": "Moulinsart"})

        response = self.do_api_request(
            self.current_url, "PATCH", self.token, data=body
        )

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_homepage_is_reported_on_the_field(self):
        body = json.dumps({"homepage": "01M209K5BNS12QRPHXFWVJ0000"})

        response = self.do_api_request(
            self.current_url, "PATCH", self.token, data=body
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn(
            "homepage", json.dumps(response.json()["detail"])
        )

    # ------------------------------------------
    # The surface that must NOT exist
    # ------------------------------------------

    def test_delete_is_not_allowed(self):
        """Regression guard for the `ModelController` trap.

        `DeleteModelControllerMixin.add_routes_to` is gated on `if cls.model:`
        alone, with no schema switch, so inheriting `ModelController` would
        register `DELETE /{id}/` -- and `_get_action_permissions` returns `[]`
        for a key absent from `permission_map`, leaving the site's settings
        deletable by any authenticated token. Composing the mixins by hand is
        what prevents it, and this test is what would notice a revert.

        405 and not 404: `/{id}/` does exist, for GET and PATCH.
        """
        response = self.do_api_request(
            f"{self.url}{self.website.pk}/", "DELETE", self.token
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Website.objects.filter(pk=self.website.pk).exists())

    @parameterized.expand(["GET", "POST"])
    def test_the_collection_path_has_no_route_at_all(self, method):
        """No list and no create, so the collection path is unrouted.

        404 rather than the 405 that `/{id}/` answers, and the difference is the
        point: nothing is registered here, so django never reaches a view to
        reject the method. Asserting 405 would be asserting that a route exists.
        """
        body = json.dumps({"name": "Nope", "headline": "Nope"})

        response = self.do_api_request(self.url, method, self.token, data=body)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Website.objects.count(), 1)

    # ------------------------------------------
    # Permissions
    # ------------------------------------------

    @parameterized.expand([
        ("GET", "totem.website.update"),
        ("PATCH", "totem.website.read"),
    ])
    def test_each_operation_requires_its_own_scope(self, method, wrong_scope):
        self.user_access_token_frodon.scope = wrong_scope
        self.user_access_token_frodon.save()
        # A valid body: ninja validates before the view runs, so an empty one
        # would answer 422 without reaching the permission check.
        body = json.dumps({"name": "Nope"})

        response = self.do_api_request(
            self.current_url, method, self.token, data=body
        )

        self.assertEqual(response.status_code, 403)

    def test_without_a_token_is_401(self):
        # Django's client directly: `do_api_request` builds the header by
        # concatenating the token, so it cannot express "no token at all".
        response = Client().get(self.current_url)

        self.assertEqual(response.status_code, 401)
