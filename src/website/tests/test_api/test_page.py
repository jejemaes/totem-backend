from django.test import TestCase
from django.utils.dateparse import parse_datetime
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.tests.test_api.common import USER_ID1, USER_ID2
from website.models import Menu, Page, Website

from .common import (
    MENU_ID4,
    MENU_ID5,
    PAGE_ID1,
    PAGE_ID2,
    PAGE_ID3,
    PAGE_SCOPES,
    PERMISSION_DENIED,
    WEBSITE_ID,
    CommonTestMixin,
)

PAGE_ID4 = "01M209K5BNS12QRPHXFWVJ0000"  # matches no page

ALL_PAGE_IDS = [PAGE_ID1, PAGE_ID2, PAGE_ID3]

PAGE_FIELDS = [
    "id",
    "title",
    "slug",
    "content",
    "is_published",
    "date_published",
    "update_date",
    "user",
    "layout",
]


class PageAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Frodon acts through the role every user of `CommonTestMixin` holds. It is
        # granted the whole page API and no rule here; the access tests narrow it.
        cls.role.permissions = PAGE_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/pages/"
        cls.url_detail = f"/api/v1/website/pages/{PAGE_ID2}/"
        # Rivendell: the one page neither a menu item nor the site points to, so
        # the one a plain delete can remove (both relations are `PROTECT`).
        cls.url_delete = f"/api/v1/website/pages/{PAGE_ID3}/"
        cls.payload_create = {
            "title": "Lothlorien",
            "slug": "lothlorien",
            "content": "<p>The Golden Wood</p>",
            "user": USER_ID1,
        }
        cls.payload_update = {
            "title": "Barad-dur",
            "slug": "barad-dur",
            "content": "<p>The Dark Tower</p>",
            "layout": "narrow",
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_PAGE_IDS))
        # Default ordering is by title.
        self.assertEqual([item["id"] for item in data["results"]], [PAGE_ID2, PAGE_ID3, PAGE_ID1])

        for item in data["results"]:
            self.assert_api_format(item, Page.objects.get(pk=item["id"]))

    def test_list_response_without_author(self):
        # The relation unset: the key is still there, `null`.
        response = self.do_request("GET", self.url, params={"slug": "rivendell"})
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(item["user"])
        self.assert_api_format(item, self.page_rivendell)

    @parameterized.expand(
        [
            ({"title": "shi"}, [PAGE_ID1]),
            ({"slug": "mordor"}, [PAGE_ID2]),
            ({"slug": "mor"}, []),  # `slug` is an exact match
            ({"is_published": True}, [PAGE_ID1, PAGE_ID3]),
            ({"is_published": False}, [PAGE_ID2]),
            ({"author": USER_ID1}, [PAGE_ID1]),
            ({"author": USER_ID2}, [PAGE_ID2]),
            ({"layout": "full-width"}, ALL_PAGE_IDS),
            ({"layout": "narrow"}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, Page.objects.get(pk=item["id"]))

    def test_list_filters_by_layout(self):
        Page.objects.filter(pk=PAGE_ID1).update(layout="narrow")

        response = self.do_request("GET", self.url, params={"layout": "narrow"})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in data["results"]], [PAGE_ID1])

    @parameterized.expand(
        [
            ({"is_published": "not a boolean"}, "is_published"),
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["title", "id"]),  # default
            (["title"], ["title", "id"]),
            (["-title"], ["-title", "id"]),
            (["slug"], ["slug", "id"]),
            (["-slug"], ["-slug", "id"]),
            (["is_published"], ["is_published", "id"]),
            (["-is_published"], ["-is_published", "id"]),
            (["layout", "title"], ["layout", "title", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(Page.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    def test_list_ordering_by_update_date(self):
        # The pages are bulk created together; touching one makes it the latest.
        Page.objects.filter(pk=PAGE_ID2).update(title="Mordor")

        response = self.do_request("GET", self.url, params={"ordering": "-update_date"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["id"], PAGE_ID2)

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], PAGE_FIELDS, 6),  # default means all fields: the author prefetched
            (["title"], ["id", "title"], 5),  # `id` is always returned
            (["title", "slug", "layout"], ["id", "title", "slug", "layout"], 5),
            (["user"], ["id", "user"], 6),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_PAGE_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Page.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "user"],),  # with a relation
            (["url"],),  # a property of the model, not a field of the schema
            (["author"],),  # a filter name is not a field
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("shire", [PAGE_ID1]),  # the title
            ("RIVEN", [PAGE_ID3]),  # case insensitive
            ("or", [PAGE_ID2]),  # "Mordor", in the title and the slug
            ("isengard", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.read"], 200),
            (["totem.websitepage.create", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.read"], 403),
        ]
    )
    def test_list_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.read"], 200),
            (["totem.websitepage.create", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.read"], 403),
        ]
    )
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], ALL_PAGE_IDS),
            # Frodon's page only: neither Gollum's nor the one with no author.
            (["website_manage_own_page"], [PAGE_ID1]),
        ]
    )
    def test_list_user_access_rules(self, rules, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ([],),
            (["website_manage_own_page"],),
        ]
    )
    def test_list_apikey_access_rules(self, rules):
        # A key has no user, hence no role: whatever the rules of the roles, it
        # reads every page. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(ALL_PAGE_IDS))

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", f"{self.url}{PAGE_ID1}/")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, self.page_shire)
        self.assertEqual(data["layout"], "full-width")
        self.assertIsNotNone(data["date_published"])

    def test_retrieve_response_draft(self):
        # A draft has never been published: no publication date.
        response = self.do_request("GET", self.url_detail)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, self.page_mordor)
        self.assertIsNone(data["date_published"])

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{PAGE_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.read"], 200),
            (["totem.websitepage.create", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.read"], 403),
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
            (["totem.websitepage.read"], 200),
            (["totem.websitepage.create", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.read"], 403),
        ]
    )
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], PAGE_ID2, 200),
            (["website_manage_own_page"], PAGE_ID1, 200),
            (["website_manage_own_page"], PAGE_ID2, 404),  # out of reach reads as missing
            (["website_manage_own_page"], PAGE_ID3, 404),  # no author is nobody's own
        ]
    )
    def test_retrieve_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"{self.url}{pk}/")

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["id"], pk)

    @parameterized.expand(
        [
            ([],),
            (["website_manage_own_page"],),
        ]
    )
    def test_retrieve_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], PAGE_ID2)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"title": None}, 422),
            ({"slug": None}, 422),
            ({"slug": "not a slug"}, 422),
            # The `page_unique_slug` constraint, mapped by
            # `_database_error_to_validation_error` and its violation message.
            ({"slug": "shire"}, 422),
            ({"content": None}, 422),
            # The `HtmlField` validators become pydantic validators on the
            # schema, so the content never reaches the service.
            ({"content": "<p onclick=\"alert('nazgul')\">x</p>"}, 422),
            # The `choices` enum answers before any service hook could, naming
            # every valid id: why `PageService` carries no layout validation.
            ({"layout": "no-such-layout"}, 422),
            ({"layout": "narrow"}, 201),
            ({"user": None}, 201),
            ({"user": "5263de93-e694-11ef-b873-34610551afcd"}, 422),  # an unknown author
            ({"is_published": True}, 201),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code, response.json())
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))
            self.assertFalse(Page.objects.filter(title="Lothlorien").exists())

    def test_create_request_unknown_layout_names_the_valid_ones(self):
        response = self.do_request("POST", self.url, data={**self.payload_create, "layout": "no-such-layout"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("full-width", str(response.json()["detail"]))

    def test_create_request_duplicated_slug(self):
        response = self.do_request("POST", self.url, data={**self.payload_create, "slug": "shire"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("slug already exists", str(response.json()))
        self.assertEqual(Page.objects.filter(slug="shire").count(), 1)

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        page = Page.objects.get(pk=data["id"])
        self.assert_api_format(data, page)
        self.assertEqual(data["user"], {"id": USER_ID1, "login": "frodon@lacomte.com"})
        # A draft by default: no publication date.
        self.assertFalse(page.is_published)
        self.assertIsNone(page.date_published)

    def test_create_published_stamps_the_publication_date(self):
        # `WebsitePublishedQuerySet.bulk_create`, which is the service write path.
        response = self.do_request("POST", self.url, data={**self.payload_create, "is_published": True})
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assertIsNotNone(data["date_published"])
        self.assertIsNotNone(Page.objects.get(pk=data["id"]).date_published)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.create"], 201),
            (["totem.websitepage.read", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.create"], 403),
        ]
    )
    def test_create_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.create"], 201),
            (["totem.websitepage.read", "totem.websitepage.update", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], USER_ID1, 201),
            ([], USER_ID2, 201),
            ([], None, 201),
            (["website_manage_own_page"], USER_ID1, 201),
            # A page authored by someone else, or by nobody, is out of reach: the
            # creation is refused and nothing is written.
            (["website_manage_own_page"], USER_ID2, 403),
            (["website_manage_own_page"], None, 403),
        ]
    )
    def test_create_user_access_rules(self, rules, author, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url, data={**self.payload_create, "user": author})

        self.assertEqual(response.status_code, status_code)
        if status_code == 201:
            self.assertTrue(Page.objects.filter(pk=response.json()["id"], user_id=author).exists())
        else:
            self.assertFalse(Page.objects.filter(slug="lothlorien").exists())

    @parameterized.expand(
        [
            ([], USER_ID2),
            (["website_manage_own_page"], USER_ID2),
            (["website_manage_own_page"], None),
        ]
    )
    def test_create_apikey_access_rules(self, rules, author):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url, auth="apikey", data={**self.payload_create, "user": author})

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Page.objects.filter(pk=response.json()["id"], user_id=author).exists())

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"title": None}, 422),
            ({"slug": None}, 422),
            ({"slug": "not a slug"}, 422),
            ({"slug": "rivendell"}, 422),  # taken by another page
            ({"content": None}, 422),
            ({"content": "<p onclick=\"alert('nazgul')\">x</p>"}, 422),
            ({"layout": "no-such-layout"}, 422),
            ({"layout": None}, 422),
            ({"user": None}, 200),
            ({"user": USER_ID1}, 200),
            ({"is_published": True}, 200),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code, response.json())
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))
            self.assertEqual(Page.objects.get(pk=PAGE_ID2).title, "Mordor")

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Page.objects.get(pk=PAGE_ID2))
        self.assertEqual((data["title"], data["slug"], data["layout"]), ("Barad-dur", "barad-dur", "narrow"))

    def test_update_moves_the_update_date(self):
        before = Page.objects.get(pk=PAGE_ID2)

        response = self.do_request("PATCH", self.url_detail, data={"title": "Barad-dur"})

        self.assertEqual(response.status_code, 200)
        # `queryset.update()` does not run `auto_now`; `PageQuerySet` does.
        self.assertGreater(Page.objects.get(pk=PAGE_ID2).update_date, before.update_date)

    def test_update_publishing_stamps_the_publication_date(self):
        response = self.do_request("PATCH", self.url_detail, data={"is_published": True})

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["date_published"])
        self.assertIsNotNone(Page.objects.get(pk=PAGE_ID2).date_published)

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{PAGE_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.update"], 200),
            (["totem.websitepage.create", "totem.websitepage.read", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.update"], 403),
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
            (["totem.websitepage.update"], 200),
            (["totem.websitepage.create", "totem.websitepage.read", "totem.websitepage.delete"], 403),
            (["totem.websitemenu.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], PAGE_ID2, 200),
            (["website_manage_own_page"], PAGE_ID1, 200),
            (["website_manage_own_page"], PAGE_ID2, 404),
            (["website_manage_own_page"], PAGE_ID3, 404),
        ]
    )
    def test_update_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", f"{self.url}{pk}/", data={"title": "Weathertop"})

        self.assertEqual(response.status_code, status_code)
        # Only the page in reach was written.
        self.assertEqual(Page.objects.get(pk=pk).title == "Weathertop", status_code == 200)

    @parameterized.expand(
        [
            ([],),
            (["website_manage_own_page"],),
        ]
    )
    def test_update_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data={"title": "Weathertop"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Page.objects.get(pk=PAGE_ID2).title, "Weathertop")

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_delete)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Page.objects.filter(pk=PAGE_ID3).exists())

    @parameterized.expand(
        [
            ("behind a menu item", PAGE_ID2),
            ("homepage, and behind a menu item", PAGE_ID1),
        ]
    )
    def test_delete_protected_page(self, dummy, pk):
        # `Menu.page` and `Website.homepage` are `PROTECT`: the database refuses,
        # mapped to a 422, and the page stays.
        response = self.do_request("DELETE", f"{self.url}{pk}/")

        self.assertEqual(response.status_code, 422)
        self.assertTrue(Page.objects.filter(pk=pk).exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{PAGE_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.delete"], 204),
            (["totem.websitepage.create", "totem.websitepage.read", "totem.websitepage.update"], 403),
            (["totem.websitemenu.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_delete)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitepage.delete"], 204),
            (["totem.websitepage.create", "totem.websitepage.read", "totem.websitepage.update"], 403),
            (["totem.websitemenu.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_delete, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], PAGE_ID2, 204),
            (["website_manage_own_page"], PAGE_ID1, 204),
            (["website_manage_own_page"], PAGE_ID2, 404),
            (["website_manage_own_page"], PAGE_ID3, 404),
        ]
    )
    def test_delete_user_access_rules(self, rules, pk, status_code):
        # The Shire is the homepage of the site and both it and Mordor are behind
        # a menu item: those relations are `PROTECT`, so they are cut first to
        # test the rule alone.
        Website.objects.filter(pk=WEBSITE_ID).update(homepage=None)
        Menu.objects.filter(pk__in=[MENU_ID4, MENU_ID5]).delete()
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", f"{self.url}{pk}/")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Page.objects.filter(pk=pk).exists(), status_code != 204)

    @parameterized.expand(
        [
            ([],),
            (["website_manage_own_page"],),
        ]
    )
    def test_delete_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", self.url_delete, auth="apikey")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Page.objects.filter(pk=PAGE_ID3).exists())

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would: granting a scope is editing the role,
        never forging a token.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or PAGE_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], obj.pk)
        if "title" in fields:
            self.assertEqual(api_data["title"], obj.title)
        if "slug" in fields:
            self.assertEqual(api_data["slug"], obj.slug)
        if "content" in fields:
            self.assertEqual(api_data["content"], obj.content)
        if "is_published" in fields:
            self.assertEqual(api_data["is_published"], obj.is_published)
        # The datetimes serialize to the millisecond, not the microsecond stored.
        if "date_published" in fields:
            if obj.date_published is None:
                self.assertIsNone(api_data["date_published"])
            else:
                self.assertEqual(
                    parse_datetime(api_data["date_published"]),
                    obj.date_published.replace(microsecond=obj.date_published.microsecond // 1000 * 1000),
                )
        if "update_date" in fields:
            self.assertEqual(
                parse_datetime(api_data["update_date"]),
                obj.update_date.replace(microsecond=obj.update_date.microsecond // 1000 * 1000),
            )
        if "user" in fields:
            # The author serializes as its display name, `null` when unset.
            if obj.user_id is None:
                self.assertIsNone(api_data["user"])
            else:
                self.assertEqual(api_data["user"], {"id": str(obj.user.pk), "login": obj.user.username})
        if "layout" in fields:
            self.assertEqual(api_data["layout"], obj.layout)

        self.assertEqual(set(fields), set(api_data))
