from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from document.models import DocumentTag, DocumentTagCategory
from user.access_rights import get_user_scopes

from .common import (
    CATEGORY_EMPTY_ID,
    CATEGORY_REALM_ID,
    CATEGORY_SCOPES,
    CATEGORY_STATUS_ID,
    PERMISSION_DENIED,
    CommonTestMixin,
)

CATEGORY_ID4 = "01JD0000000000000000000099"  # matches no category

ALL_CATEGORY_IDS = [CATEGORY_STATUS_ID, CATEGORY_REALM_ID, CATEGORY_EMPTY_ID]

CATEGORY_FIELDS = ["id", "name", "sequence", "color"]

# The fields of the creation having a default; `name` has none.
CATEGORY_DEFAULT_FIELDS = ["sequence", "color"]


class DocumentTagCategoryAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for
    `DocumentTagCategory`, so whoever holds a scope reaches every category. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = CATEGORY_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/document/tag-categories/"
        cls.url_detail = f"/api/v1/document/tag-categories/{CATEGORY_REALM_ID}/"
        cls.url_default_values = "/api/v1/document/tag-categories/default-values/"
        cls.payload_create = {"name": "Kind", "sequence": 4, "color": 5}
        cls.payload_update = {"name": "Kingdom of Men", "color": 7}

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_CATEGORY_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_CATEGORY_IDS))

        for item in data["results"]:
            self.assert_api_format(item, DocumentTagCategory.objects.get(id=item["id"]))

    # No `test_list_filters` nor `test_list_invalid_filters`: the only filter is
    # the search, a string, see `test_list_searching`.

    @parameterized.expand(
        [
            ([], ["sequence", "name", "id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["-sequence"], ["-sequence", "id"]),
            (["color"], ["color", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in DocumentTagCategory.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], CATEGORY_FIELDS, 5),  # default means all fields
            (["name"], ["id", "name"], 5),  # `id` is always returned
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_CATEGORY_IDS))
        for item in data["results"]:
            self.assert_api_format(item, DocumentTagCategory.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "name"],),
            (["tags"],),  # a reverse relation the schema does not publish
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("STATUS", [CATEGORY_STATUS_ID]),  # case insensitive
            ("king", [CATEGORY_EMPTY_ID]),
            ("a", [CATEGORY_STATUS_ID, CATEGORY_REALM_ID]),
            ("mordor", []),
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
            (["totem.documenttagcategory.read"], 200),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.read"], 403),
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
            (["totem.documenttagcategory.read"], 200),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.read"], 403),
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
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), self.category_realm)

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{CATEGORY_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.documenttagcategory.read"], 200),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.read"], 403),
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
            (["totem.documenttagcategory.read"], 200),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.read"], 403),
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
            ({"name": None}, 422, "name"),
            ({"name": "Status"}, 422, None),  # taken: unkeyed
            ({"color": -1}, 422, "color"),
            ({"color": 16}, 422, "color"),
            ({"sequence": None}, 422, "sequence"),
            ({"sequence": -3}, 201, None),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, DocumentTagCategory.objects.get(id=data["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.documenttagcategory.create"], 201),
            (["totem.documenttagcategory.read", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.create"], 403),
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
            (["totem.documenttagcategory.create"], 201),
            (["totem.documenttagcategory.read", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.create"], 403),
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
    # Default Values Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 200, None),
            ({"fields": "name,color"}, 200, None),
            ({"fields": "id"}, 422, "fields"),  # not a field of the creation
        ]
    )
    def test_default_value_request(self, params, status_code, error_field):
        response = self.do_request("GET", self.url_default_values, params=params)

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand([("user",), ("apikey",)])
    def test_default_value_response(self, auth):
        response = self.do_request("GET", self.url_default_values, auth=auth)

        self.assertEqual(response.status_code, 200)
        self.assert_default_values_format(response.json(), {"sequence": 10, "color": 0})

    @parameterized.expand(
        [
            (["color"], ["color"]),
            # No default: absent, not null.
            (["name"], []),
            (["name", "sequence", "color"], CATEGORY_DEFAULT_FIELDS),
        ]
    )
    def test_default_value_query_fields(self, query_fields, received_fields):
        response = self.do_request("GET", self.url_default_values, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 200)
        self.assert_default_values_format(response.json(), {"sequence": 10, "color": 0}, received_fields)

    @parameterized.expand(
        [
            ("user", [], 403),
            ("user", ["totem.documenttagcategory.create"], 200),
            ("user", ["totem.documenttagcategory.read", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
            ("user", ["totem.documenttag.create"], 403),
            ("apikey", [], 403),
            ("apikey", ["totem.documenttagcategory.create"], 200),
            ("apikey", ["totem.documenttagcategory.read", "totem.documenttagcategory.update", "totem.documenttagcategory.delete"], 403),
        ]
    )
    def test_default_value_access_rights(self, auth, permissions, status_code):
        if auth == "apikey":
            self.api_key.scope = permissions
            self.api_key.save()
        else:
            self.role.permissions = permissions
            self.role.save()

        response = self.do_request("GET", self.url_default_values, auth=auth)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422),
            ({"name": "Status"}, 422),  # taken
            ({"color": 16}, 422),
            ({"sequence": None}, 422),
            ({"name": "Kingdom of Men"}, 200),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, DocumentTagCategory.objects.get(id=CATEGORY_REALM_ID))
        self.assertEqual((data["name"], data["color"]), ("Kingdom of Men", 7))

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{CATEGORY_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.documenttagcategory.update"], 200),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.read", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.update"], 403),
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
            (["totem.documenttagcategory.update"], 200),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.read", "totem.documenttagcategory.delete"], 403),
            (["totem.documenttag.update"], 403),
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
        response = self.do_request("DELETE", f"{self.url}{CATEGORY_EMPTY_ID}/")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(DocumentTagCategory.objects.filter(pk=CATEGORY_EMPTY_ID).exists())

    def test_delete_with_tags_is_refused(self):
        # `PROTECT`: deleting it would silently take its tags along.
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 422)
        self.assertTrue(DocumentTagCategory.objects.filter(pk=CATEGORY_REALM_ID).exists())
        self.assertTrue(DocumentTag.objects.filter(category_id=CATEGORY_REALM_ID).exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{CATEGORY_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.documenttagcategory.delete"], 204),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.read", "totem.documenttagcategory.update"], 403),
            (["totem.documenttag.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", f"{self.url}{CATEGORY_EMPTY_ID}/")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.documenttagcategory.delete"], 204),
            (["totem.documenttagcategory.create", "totem.documenttagcategory.read", "totem.documenttagcategory.update"], 403),
            (["totem.documenttag.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", f"{self.url}{CATEGORY_EMPTY_ID}/", auth="apikey")

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
        fields = fields or CATEGORY_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "sequence" in fields:
            self.assertEqual(api_data["sequence"], obj.sequence)
        if "color" in fields:
            self.assertEqual(api_data["color"], obj.color)

        self.assertEqual(set(fields), set(api_data))

    def assert_default_values_format(self, api_data, values, fields=None):
        fields = CATEGORY_DEFAULT_FIELDS if fields is None else fields

        for name in fields:
            self.assertEqual(api_data[name], values[name])

        self.assertEqual(set(fields), set(api_data))
