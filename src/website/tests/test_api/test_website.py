from django.test import Client, TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.models import Menu, Page, Website

WEBSITE_ID = "01M209K5BNS12QRPHXFWVJNVD1"
PAGE_ID = "01M209K5BNS12QRPHXFWVJNVD2"
MENU_ID = "01M209K5BNS12QRPHXFWVJNVD3"

# A well-formed but absent ULID: the schema types a relation with the target's
# primary key type, so a malformed one would be refused before the service runs.
UNKNOWN_PAGE_ID = "01M209K5BNS12QRPHXFWVJ0000"


class WebsiteAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """The site's own settings, which had no route at all before this.

    Two ways in, for one row. `/current/` is the one a client uses: the record is
    a singleton provisioned by `populate_system` under a fixed pk, so nobody has
    an id to send. `/{id}/` comes from the generated CRUD mixins and is tested
    because it exists, not because anything calls it.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.page = Page.objects.create(
            id=PAGE_ID,
            title="Le Trésor de Rackham",
            slug="tresor",
            content="<p>Mille sabords</p>",
            is_published=True,
        )
        cls.menu = Menu.objects.create(id=MENU_ID, name="Main")
        cls.website = Website.objects.create(
            id=WEBSITE_ID,
            name="Moulinsart",
            headline="Le domaine du capitaine",
            meta_authors="Hergé",
            meta_description="Le trésor de Rackham le Rouge",
            footer="<p>Tonnerre de Brest</p>",
            menu=cls.menu,
            homepage=cls.page,
        )

        cls.url = "/api/v1/website/websites/"
        cls.url_detail = f"/api/v1/website/websites/{WEBSITE_ID}/"
        cls.url_current = "/api/v1/website/websites/current/"
        cls.payload_update = {
            "name": "La Licorne",
            "headline": "Un navire",
            "meta_authors": "Tintin",
            "meta_description": "Le secret",
            "footer": "<p>Mille sabords</p>",
        }

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        # Both relations are set, so serializing them is what forces them to be
        # resolved: this covers the relational part of the payload.
        self._assert_api_format(data, self.website, None)

    def test_retrieve_not_found(self):
        response = self.do_api_request(
            f"{self.url}{UNKNOWN_PAGE_ID}/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand([
        ("totem.website.read", 200),
        ("totem.website.update", 403),
    ])
    def test_retrieve_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail, "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    def test_update_response(self):
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)

        obj = Website.objects.get(id=WEBSITE_ID)
        self.assertEqual(obj.name, "La Licorne")
        # The relations were not in the payload and must survive it, still
        # expanded in the response.
        self._assert_api_format(data, obj, None)

    @parameterized.expand([
        ({"name": None}, 422, "name"),
        ({"headline": None}, 422, "headline"),
        ({"meta_authors": None}, 200, None),
        ({"meta_description": None}, 200, None),
        ({"footer": None}, 200, None),
        ({"homepage": None}, 200, None),
        ({"menu": None}, 200, None),
        ({"homepage": UNKNOWN_PAGE_ID}, 422, "homepage"),
        ({"menu": UNKNOWN_PAGE_ID}, 422, "menu"),
        ({"footer": '<t-widget name="nope"></t-widget>'}, 422, "footer"),
    ])
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        """`name` and `headline` are NOT NULL, everything else here is nullable.

        Each refusal is asserted on the field it names, not just on the status:
        every row below would still be a 422 if it started failing for an
        unrelated reason, and three quite different mechanisms produce these.
        `null` on a non-null column is `ServiceBase.to_internal_values` --
        `optional_fields = "__all__"` types every field `Optional`, so the schema
        lets it through and without that check it would reach the database as an
        unkeyed integrity error. The relation rows are the scoped resolution
        through `browse`. The `footer` row is `HtmlField(allow_widget=True)`
        refusing a marker that names no registered widget.
        """
        data = dict(self.payload_update)
        data.update(extra_body)

        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data=data
        )

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual(
                [detail["loc"][-1] for detail in response.json()["detail"]],
                [error_field],
            )

    @parameterized.expand([
        ("totem.website.read", 403),
        ("totem.website.update", 200),
    ])
    def test_update_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Read Current Operation
    # ------------------------------------------

    def test_current_read_response(self):
        response = self.do_api_request(
            self.url_current, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(data, self.website, None)

    def test_current_read_response_without_relations(self):
        """A freshly provisioned site has no homepage and no main menu yet.

        The state `HomePageView` degrades on, so the payload has to express it:
        `null`, and the keys still present -- an editor reading the settings to
        offer "pick a homepage" needs to see the field, not have it disappear.
        """
        Website.objects.filter(pk=WEBSITE_ID).update(menu=None, homepage=None)
        self.website.refresh_from_db()

        response = self.do_api_request(
            self.url_current, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(data["menu"])
        self.assertIsNone(data["homepage"])
        self._assert_api_format(data, self.website, None)

    def test_current_read_wins_the_path_match_against_the_id_route(self):
        """Load-bearing registration order, so it gets its own test.

        `BaseController.add_routes_to` sorts by `list(cls.__dict__).index(name)`.
        `current_read` is in `__dict__` from the class body, while `retrieve` is
        only put there later by `method_to_route_function`, so `/current/` is
        registered first. If that ever inverted, this request would be matched by
        `retrieve` with `id="current"` and answer 404.
        """
        response = self.do_api_request(
            self.url_current, "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], WEBSITE_ID)

    def test_current_read_not_found_on_an_unpopulated_database(self):
        Website.objects.all().delete()

        response = self.do_api_request(
            self.url_current, "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    @parameterized.expand([
        ("totem.website.read", 200),
        ("totem.website.update", 403),
    ])
    def test_current_read_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_current, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    def test_current_read_without_a_token_is_unauthorized(self):
        # Django's client directly: `do_api_request` builds the header by
        # concatenating the token, so it cannot express "no token at all".
        response = Client().get(self.url_current)

        self.assertEqual(response.status_code, 401)

    # ------------------------------------------
    # Update Current Operation
    # ------------------------------------------

    def test_current_update_response(self):
        response = self.do_api_request(
            self.url_current,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)

        obj = Website.objects.get(id=WEBSITE_ID)
        self.assertEqual(obj.name, "La Licorne")
        self.assertEqual(obj.footer, "<p>Mille sabords</p>")
        self._assert_api_format(data, obj, None)

    def test_current_update_not_found_on_an_unpopulated_database(self):
        Website.objects.all().delete()

        response = self.do_api_request(
            self.url_current,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Website.objects.count(), 0)

    @parameterized.expand([
        ("totem.website.read", 403),
        ("totem.website.update", 200),
    ])
    def test_current_update_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_current,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Operations that must NOT exist
    # ------------------------------------------

    def test_delete_is_not_allowed(self):
        """Regression guard for the `ModelController` trap.

        `DeleteModelControllerMixin.add_routes_to` is gated on `if cls.model:`
        alone, with no schema switch, so inheriting `ModelController` would
        register `DELETE /{id}/` -- and `_get_action_permissions` returns `[]`
        for a key absent from `permission_map`, leaving the site's settings
        deletable by any authenticated token. Composing the mixins by hand is
        what prevents it, and this is what would notice a revert.

        405 and not 404: `/{id}/` does exist, for GET and PATCH.
        """
        response = self.do_api_request(
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Website.objects.filter(pk=WEBSITE_ID).exists())

    @parameterized.expand(["GET", "POST"])
    def test_the_collection_path_has_no_route(self, method):
        """No list and no create, so the collection path is unrouted.

        404 rather than the 405 `/{id}/` answers, and the difference is the
        point: nothing is registered here, so django never reaches a view to
        reject the method. Asserting 405 would be asserting a route exists.
        """
        response = self.do_api_request(
            self.url, method, self.user_access_token_frodon.token,
            data=self.payload_update,
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Website.objects.count(), 1)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(
        self, api_data, obj, fields, expand=True
    ):  # pylint: disable=unused-argument
        if not fields:
            fields = [
                "id",
                "name",
                "headline",
                "meta_authors",
                "meta_description",
                "menu",
                "homepage",
                "footer",
            ]

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

        # Display-name objects rather than bare pks: the editor needs a label to
        # show. Asserting the nested shape is also what proves the relation was
        # resolved before serialization -- ninja serializes outside any
        # `sync_to_async` hop, so an unresolved one raises
        # `SynchronousOnlyOperation` instead of returning a pk.
        if "menu" in fields:
            if obj.menu_id:
                self.assertEqual(
                    api_data["menu"], {"id": obj.menu.pk, "name": obj.menu.name}
                )
            else:
                self.assertIsNone(api_data["menu"])
        if "homepage" in fields:
            if obj.homepage_id:
                self.assertEqual(
                    api_data["homepage"],
                    {
                        "id": obj.homepage.pk,
                        "title": obj.homepage.title,
                        "slug": obj.homepage.slug,
                    },
                )
            else:
                self.assertIsNone(api_data["homepage"])

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
