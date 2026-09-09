import json

from django.test import TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.models import Menu, Page

ALL_SCOPES = (
    "totem.websitemenu.create totem.websitemenu.read "
    "totem.websitemenu.update totem.websitemenu.delete"
)


class MenuAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """
    Root
     |- Presentation (10, link)
     |- Activities   (25, link)
         |- Hike (10, page)
         |- Camp (45, page)
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.page_hike = Page.objects.create(
            title="Le Hike", slug="hike", content="<p>x</p>", is_published=True
        )
        cls.page_camp = Page.objects.create(
            title="Le Camp", slug="camp", content="<p>x</p>", is_published=True
        )

        cls.root = Menu.objects.create(name="Root", sequence=20)
        cls.presentation = Menu.objects.create(
            name="Presentation", parent=cls.root, sequence=10, link="/p/"
        )
        cls.activities = Menu.objects.create(
            name="Activities", parent=cls.root, sequence=25, link="#"
        )
        cls.hike = Menu.objects.create(
            name="Hike", parent=cls.activities, sequence=10, page=cls.page_hike
        )
        cls.camp = Menu.objects.create(
            name="Camp", parent=cls.activities, sequence=45, page=cls.page_camp
        )

        cls.user_access_token_frodon.scope = ALL_SCOPES
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/website/menus/"

    @property
    def token(self):
        return self.user_access_token_frodon.token

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_api_request(self.url, "GET", self.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], 5)
        # Default ordering is by sequence, then name.
        self.assertEqual(
            [item["name"] for item in data["results"]],
            ["Hike", "Presentation", "Root", "Activities", "Camp"],
        )

    def test_list_serializes_relations_as_nested_objects(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"search": "hike"}
        )
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            item["parent"], {"id": self.activities.pk, "name": "Activities"}
        )
        self.assertEqual(
            item["page"],
            {"id": self.page_hike.pk, "title": "Le Hike", "slug": "hike"},
        )

    def test_list_keeps_the_null_relations_of_a_root(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"search": "root"}
        )
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(item["parent"])
        self.assertIsNone(item["page"])

    @parameterized.expand([
        ({"name": "act"}, ["Activities"]),
        ({"search": "camp"}, ["Camp"]),
        ({"search": "/p/"}, ["Presentation"]),
        ({"search": "nothing"}, []),
    ])
    def test_list_filters(self, filters, expected):
        response = self.do_api_request(self.url, "GET", self.token, params=filters)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.json()["results"]], expected
        )

    def test_list_filter_by_parent(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"parent": self.root.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.json()["results"]],
            ["Presentation", "Activities"],
        )

    def test_list_filter_by_target_page(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"target_page": self.page_camp.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.json()["results"]], ["Camp"]
        )

    def test_list_filter_by_root_returns_the_whole_subtree(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"root": self.root.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 5)

    def test_list_filter_by_root_only_matches_a_top_level_item(self):
        # `root` is a `parent_path__startswith` on the pk itself, and a path
        # always starts at a top-level item, so an inner node is not a prefix of
        # anything. Asserted so the limitation stays known -- `read_tree` used to
        # share it and no longer does: it filters on the root's own path.
        response = self.do_api_request(
            self.url, "GET", self.token, params={"root": self.activities.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)

    @parameterized.expand([
        ("name", ["Activities", "Camp", "Hike", "Presentation", "Root"]),
        ("-name", ["Root", "Presentation", "Hike", "Camp", "Activities"]),
        # An explicit `sequence` replaces the default `sequence, name`, so the
        # two items at 10 fall back on the pk appended by
        # `queryset_order_by_fields` -- i.e. on creation order, which is what a
        # ULID makes meaningful. `Presentation` was created before `Hike`.
        ("sequence", ["Presentation", "Hike", "Root", "Activities", "Camp"]),
    ])
    def test_list_ordering(self, ordering, expected):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"ordering": ordering}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["name"] for item in response.json()["results"]], expected
        )

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(f"{self.url}{self.hike.pk}/", "GET", self.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["id"], self.hike.pk)
        self.assertEqual(len(data["id"]), 26)
        self.assertEqual(data["sequence"], 10)
        self.assertEqual(
            data["parent_path"],
            f"{self.root.pk}/{self.activities.pk}/{self.hike.pk}/",
        )

    def test_retrieve_unknown(self):
        response = self.do_api_request(
            f"{self.url}01ARZ3NDEKTSV4RRFFQ69G5FAV/", "GET", self.token
        )

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    def test_create_a_root(self):
        # The `menu_page_or_link` constraint exempts roots: they are containers,
        # not destinations.
        response = self.do_api_request(
            self.url, "POST", self.token, data=json.dumps({"name": "Other Root"})
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(len(data["id"]), 26)
        self.assertIsNone(data["parent"])
        self.assertEqual(data["parent_path"], f"{data['id']}/")

    def test_create_a_child_materializes_the_path(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({
                "name": "Atout Camp",
                "parent": self.activities.pk,
                "link": "https://www.atoutscamps.be/",
            }),
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(
            data["parent_path"],
            f"{self.root.pk}/{self.activities.pk}/{data['id']}/",
        )

    def test_create_a_child_targeting_a_page(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({
                "name": "Le Camp",
                "parent": self.root.pk,
                "page": self.page_camp.pk,
            }),
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(data["page"]["slug"], "camp")

    def test_create_a_child_without_a_link_or_a_page_is_rejected(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({"name": "Bad", "parent": self.root.pk}),
        )

        self.assertEqual(response.status_code, 422, response.json())
        self.assertIn(
            "Menu must be linked to an URL or a page.", json.dumps(response.json())
        )
        self.assertFalse(Menu.objects.filter(name="Bad").exists())

    def test_create_with_an_unknown_parent_is_rejected(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({
                "name": "Bad", "parent": "01ARZ3NDEKTSV4RRFFQ69G5FAV", "link": "/a/",
            }),
        )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Menu.objects.filter(name="Bad").exists())

    def test_create_cannot_write_the_materialized_path(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({"name": "Other Root", "parent_path": "forged/"}),
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(data["parent_path"], f"{data['id']}/")

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    def test_update_response(self):
        response = self.do_api_request(
            f"{self.url}{self.camp.pk}/", "PATCH", self.token,
            data=json.dumps({"name": "Le Camp Scout", "sequence": 30}),
        )

        self.assertEqual(response.status_code, 200, response.json())
        menu = Menu.objects.get(pk=self.camp.pk)
        self.assertEqual(menu.name, "Le Camp Scout")
        self.assertEqual(menu.sequence, 30)

    def test_update_the_parent_recomputes_the_subtree(self):
        response = self.do_api_request(
            f"{self.url}{self.activities.pk}/", "PATCH", self.token,
            data=json.dumps({"parent": self.presentation.pk}),
        )

        self.assertEqual(response.status_code, 200, response.json())
        # `MenuQuerySet.update` walks the whole table, so a grandchild follows.
        self.assertEqual(
            Menu.objects.get(pk=self.hike.pk).parent_path,
            f"{self.root.pk}/{self.presentation.pk}/"
            f"{self.activities.pk}/{self.hike.pk}/",
        )

    def test_update_to_its_own_parent_is_rejected(self):
        response = self.do_api_request(
            f"{self.url}{self.activities.pk}/", "PATCH", self.token,
            data=json.dumps({"parent": self.activities.pk}),
        )

        self.assertEqual(response.status_code, 422, response.json())
        self.assertIn(
            "cannot be its own parent", json.dumps(response.json())
        )

    def test_update_under_its_own_child_is_rejected(self):
        # `recompute_parent_store` walks down from the roots, so a cycle is not
        # an error there: the rows just become unreachable. Hence the guard in
        # `MenuService.validate_data`.
        response = self.do_api_request(
            f"{self.url}{self.activities.pk}/", "PATCH", self.token,
            data=json.dumps({"parent": self.hike.pk}),
        )

        self.assertEqual(response.status_code, 422, response.json())
        self.assertIn(
            "cannot be moved under one of its own children",
            json.dumps(response.json()),
        )
        self.assertEqual(
            Menu.objects.get(pk=self.activities.pk).parent_id, self.root.pk
        )

    def test_update_unparents_to_a_root(self):
        response = self.do_api_request(
            f"{self.url}{self.activities.pk}/", "PATCH", self.token,
            data=json.dumps({"parent": None}),
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(
            Menu.objects.get(pk=self.activities.pk).parent_path,
            f"{self.activities.pk}/",
        )

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_a_leaf(self):
        response = self.do_api_request(f"{self.url}{self.camp.pk}/", "DELETE", self.token)

        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(Menu.objects.filter(pk=self.camp.pk).exists())

    # ------------------------------------------
    # Permissions
    # ------------------------------------------

    @parameterized.expand([
        ("GET", "totem.websitemenu.create"),
        ("POST", "totem.websitemenu.read"),
        ("PATCH", "totem.websitemenu.read"),
        ("DELETE", "totem.websitemenu.read"),
    ])
    def test_operation_requires_its_own_scope(self, method, wrong_scope):
        self.user_access_token_frodon.scope = wrong_scope
        self.user_access_token_frodon.save()
        url = self.url if method in ("GET", "POST") else f"{self.url}{self.camp.pk}/"
        # A valid body: ninja validates it before the view runs, so an empty one
        # would answer 422 without ever reaching the permission check.
        body = json.dumps({"name": "Nope"})

        response = self.do_api_request(url, method, self.token, data=body)

        self.assertEqual(response.status_code, 403)
