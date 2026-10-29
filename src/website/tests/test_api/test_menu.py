import datetime

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Menu

from .common import (
    MENU_ID1,
    MENU_ID2,
    MENU_ID3,
    MENU_ID4,
    MENU_ID5,
    MENU_SCOPES,
    PAGE_ID1,
    PAGE_ID3,
    PERMISSION_DENIED,
    CommonTestMixin,
)

# Well-formed but absent ULIDs: the schema types a relation with the target's
# primary key type, so a malformed one is refused before the service runs.
UNKNOWN_MENU_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
UNKNOWN_PAGE_ID = "01M209K5BNS12QRPHXFWVJ0000"

ALL_MENU_IDS = [MENU_ID1, MENU_ID2, MENU_ID3, MENU_ID4, MENU_ID5]

MENU_FIELDS = ["id", "name", "parent", "parent_path", "sequence", "page", "link", "new_window", "create_date"]


@freeze_time("2026-10-15 11:12:13")
class MenuAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The menu items, on the tree of `CommonTestMixin`:

        Middle-earth (20)
         |- The Fellowship (10, link)
         |- Journeys       (25, link)
             |- The Shire  (10, page)
             |- Mordor     (45, page)

    No `*_access_rules` tests: no `BaseRule` is registered for `Menu`, so there
    is no rule a role could hold to narrow them. Add them with the first one.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = MENU_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/menus/"
        cls.url_detail = f"/api/v1/website/menus/{MENU_ID5}/"
        cls.payload_create = {"name": "Rivendell", "parent": MENU_ID3, "link": "/rivendell/"}
        cls.payload_update = {"name": "Barad-dur", "sequence": 30}

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_MENU_IDS))
        # Default ordering is by sequence, then name.
        self.assertEqual(
            [item["id"] for item in data["results"]],
            [MENU_ID2, MENU_ID4, MENU_ID1, MENU_ID3, MENU_ID5],
        )

        for item in data["results"]:
            self.assert_api_format(item, Menu.objects.get(pk=item["id"]))

    def test_list_response_relations(self):
        # A relation serializes as its display name; a root keeps both keys, null.
        results = {item["id"]: item for item in self.do_request("GET", self.url).json()["results"]}

        self.assertEqual(results[MENU_ID4]["parent"], {"id": MENU_ID3, "name": "Journeys"})
        self.assertEqual(results[MENU_ID4]["page"], {"id": PAGE_ID1, "title": "The Shire", "slug": "shire"})
        self.assertIsNone(results[MENU_ID1]["parent"])
        self.assertIsNone(results[MENU_ID1]["page"])

    @parameterized.expand(
        [
            ({"name": "journ"}, [MENU_ID3]),
            ({"name": "the"}, [MENU_ID2, MENU_ID4]),
            ({"parent": MENU_ID1}, [MENU_ID2, MENU_ID3]),
            ({"parent": MENU_ID3}, [MENU_ID4, MENU_ID5]),
            ({"target_page": PAGE_ID1}, [MENU_ID4]),
            ({"target_page": PAGE_ID3}, []),
            # `root` returns the whole subtree, the root included.
            ({"root": MENU_ID1}, ALL_MENU_IDS),
            # `root` is a `parent_path__startswith` on the pk itself, and a path
            # always starts at a top-level item: an inner node matches nothing.
            # Pinned so the limitation stays known.
            ({"root": MENU_ID3}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

    # No `test_list_invalid_filters`: every filter of `MenuFilterSchema` is a
    # string, so no value can fail to parse -- an id that is not a ULID matches
    # nothing rather than answering 422.

    @parameterized.expand(
        [
            ([], ["sequence", "name", "id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            # An explicit `sequence` replaces the default `sequence, name`: the two
            # items at 10 fall back on the pk, i.e. on the creation order a ULID
            # makes meaningful.
            (["sequence"], ["sequence", "id"]),
            (["-sequence"], ["-sequence", "id"]),
            (["create_date"], ["create_date", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(Menu.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    @parameterized.expand(
        [
            (["parent_path"],),  # readable, but not an ordering field
            (["not_a_field"],),
        ]
    )
    def test_list_invalid_ordering(self, ordering_fields):
        response = self.do_request("GET", self.url, params={"ordering": ",".join(ordering_fields)})

        self.assertEqual(response.status_code, 422)

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], MENU_FIELDS, 7),  # default means all fields: parent and page prefetched
            (["name"], ["id", "name"], 5),  # `id` is always returned
            (["name", "parent"], ["id", "name", "parent"], 6),
            (["page", "link"], ["id", "page", "link"], 6),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_MENU_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Menu.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "parent"],),  # with a relation
            (["url"],),  # `Menu.url` is not exposed: it would query while serializing
            (["children"],),  # a reverse relation the schema does not publish
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("shire", [MENU_ID4]),  # the name
            ("/fellowship/", [MENU_ID2]),  # the link
            ("MORDOR", [MENU_ID5]),  # case insensitive
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
            (["totem.websitemenu.read"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.read"], 403),
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
            (["totem.websitemenu.read"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.read"], 403),
        ]
    )
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", f"{self.url}{MENU_ID4}/")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Menu.objects.get(pk=MENU_ID4))
        self.assertEqual(data["parent_path"], f"{MENU_ID1}/{MENU_ID3}/{MENU_ID4}/")

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{UNKNOWN_MENU_ID}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.read"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
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
            (["totem.websitemenu.read"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
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
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 201, None),
            # A root needs neither a link nor a page: the `menu_page_or_link`
            # constraint exempts it, it is a container and not a destination.
            ({"parent": None, "link": None}, 201, None),
            ({"link": None, "page": PAGE_ID3}, 201, None),
            ({"name": None}, 422, "name"),
            ({"sequence": "first"}, 422, "sequence"),
            ({"link": None}, 422, "Menu must be linked to an URL or a page."),
            ({"parent": UNKNOWN_MENU_ID}, 422, "parent"),
            ({"parent": "not-a-ulid"}, 422, "parent"),
            ({"link": None, "page": UNKNOWN_PAGE_ID}, 422, "page"),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code, response.json())
        if status_code == 422:
            self.assertIn(error, str(response.json()))
            self.assertFalse(Menu.objects.filter(name="Rivendell").exists())

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, Menu.objects.get(pk=data["id"]))
        self.assertEqual(len(data["id"]), 26)
        # The path is materialized on creation, below the parent's.
        self.assertEqual(data["parent_path"], f"{MENU_ID1}/{MENU_ID3}/{data['id']}/")

    def test_create_response_root(self):
        response = self.do_request("POST", self.url, data={"name": "Valinor"})
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(data["parent"])
        self.assertEqual(data["parent_path"], f"{data['id']}/")

    def test_create_cannot_write_the_materialized_path(self):
        response = self.do_request("POST", self.url, data={"name": "Valinor", "parent_path": "forged/"})
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(data["parent_path"], f"{data['id']}/")

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.create"], 201),
            (["totem.websitemenu.read", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.create"], 403),
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
            (["totem.websitemenu.create"], 201),
            (["totem.websitemenu.read", "totem.websitemenu.update", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            (MENU_ID5, {"name": "Barad-dur"}, 200, None),
            # Unparenting makes a root, which needs no link.
            (MENU_ID3, {"parent": None}, 200, None),
            (MENU_ID5, {"name": None}, 422, "name"),
            (MENU_ID5, {"sequence": "first"}, 422, "sequence"),
            (MENU_ID5, {"parent": UNKNOWN_MENU_ID}, 422, "parent"),
            (MENU_ID5, {"page": UNKNOWN_PAGE_ID}, 422, "page"),
            (MENU_ID3, {"parent": MENU_ID3}, 422, "cannot be its own parent"),
            # `recompute_parent_store` walks down from the roots, so a cycle is
            # no error there: the rows would just become unreachable. Hence the
            # guard in `MenuService.validate_data`.
            (MENU_ID3, {"parent": MENU_ID4}, 422, "cannot be moved under one of its own children"),
        ]
    )
    def test_update_request_field_validation(self, pk, body, status_code, error):
        before = Menu.objects.get(pk=pk)

        response = self.do_request("PATCH", f"{self.url}{pk}/", data=body)

        self.assertEqual(response.status_code, status_code, response.json())
        if status_code == 422:
            self.assertIn(error, str(response.json()))
            after = Menu.objects.get(pk=pk)
            self.assertEqual((after.name, after.parent_id), (before.name, before.parent_id))

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        obj = Menu.objects.get(pk=MENU_ID5)
        self.assert_api_format(response.json(), obj)
        self.assertEqual((obj.name, obj.sequence), ("Barad-dur", 30))

    def test_update_the_parent_recomputes_the_subtree(self):
        response = self.do_request("PATCH", f"{self.url}{MENU_ID3}/", data={"parent": MENU_ID2})

        self.assertEqual(response.status_code, 200, response.json())
        # `MenuQuerySet.update` walks the whole table, so a grandchild follows.
        self.assertEqual(
            Menu.objects.get(pk=MENU_ID4).parent_path,
            f"{MENU_ID1}/{MENU_ID2}/{MENU_ID3}/{MENU_ID4}/",
        )

    def test_update_unparents_to_a_root(self):
        response = self.do_request("PATCH", f"{self.url}{MENU_ID3}/", data={"parent": None})

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(Menu.objects.get(pk=MENU_ID3).parent_path, f"{MENU_ID3}/")
        self.assertEqual(Menu.objects.get(pk=MENU_ID5).parent_path, f"{MENU_ID3}/{MENU_ID5}/")

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{UNKNOWN_MENU_ID}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.update"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.read", "totem.websitemenu.delete"], 403),
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
            (["totem.websitemenu.update"], 200),
            (["totem.websitemenu.create", "totem.websitemenu.read", "totem.websitemenu.delete"], 403),
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
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Menu.objects.filter(pk=MENU_ID5).exists())

    def test_delete_an_item_with_children(self):
        # `parent` is `on_delete=PROTECT`: a subtree is never deleted implicitly.
        response = self.do_request("DELETE", f"{self.url}{MENU_ID3}/")

        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(Menu.objects.filter(pk__in=[MENU_ID3, MENU_ID4, MENU_ID5]).count(), 3)

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{UNKNOWN_MENU_ID}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.delete"], 204),
            (["totem.websitemenu.create", "totem.websitemenu.read", "totem.websitemenu.update"], 403),
            (["totem.websitepage.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.delete"], 204),
            (["totem.websitemenu.create", "totem.websitemenu.read", "totem.websitemenu.update"], 403),
            (["totem.websitepage.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

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
        fields = fields or MENU_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], obj.pk)
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "parent" in fields:
            # A relation serializes as its display name, `null` when unset.
            self.assertEqual(
                api_data["parent"],
                {"id": obj.parent.pk, "name": obj.parent.name} if obj.parent else None,
            )
        if "parent_path" in fields:
            self.assertEqual(api_data["parent_path"], obj.parent_path)
        if "sequence" in fields:
            self.assertEqual(api_data["sequence"], obj.sequence)
        if "page" in fields:
            self.assertEqual(
                api_data["page"],
                {"id": obj.page.pk, "title": obj.page.title, "slug": obj.page.slug} if obj.page else None,
            )
        if "link" in fields:
            self.assertEqual(api_data["link"], obj.link)
        if "new_window" in fields:
            self.assertEqual(api_data["new_window"], obj.new_window)
        if "create_date" in fields:
            self.assertEqual(
                datetime.datetime.fromisoformat(api_data["create_date"].replace("Z", "+00:00")),
                obj.create_date,
            )

        self.assertEqual(set(fields), set(api_data))
