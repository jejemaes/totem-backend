from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from contact.models import Contact, ContactTag
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    CONTACT_ID1,
    CONTACT_ID2,
    PERMISSION_DENIED,
    TAG_ID1,
    TAG_ID2,
    TAG_ID3,
    TAG_SCOPES,
    CommonTestMixin,
)

TAG_ID4 = "01JT0000000000000000000099"  # matches no tag

ALL_TAG_IDS = [TAG_ID1, TAG_ID2, TAG_ID3]

TAG_FIELDS = ["id", "name", "color"]


class ContactTagAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `ContactTag`, so
    whoever holds a scope reaches every tag. Add them with the first rule. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = TAG_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/contact-tags/"
        cls.url_detail = f"/api/v1/contact-tags/{TAG_ID2}/"
        cls.payload_create = {"name": "Ranger", "color": 7}
        cls.payload_update = {"name": "Halfling", "color": 6}

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_TAG_IDS))
        # By name, the default ordering.
        self.assertEqual([item["id"] for item in data["results"]], [TAG_ID1, TAG_ID2, TAG_ID3])

        for item in data["results"]:
            self.assert_api_format(item, ContactTag.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"name": "hob"}, [TAG_ID2]),  # case insensitive
            ({"name": "i"}, [TAG_ID1, TAG_ID2, TAG_ID3]),
            ({"name": "Nazgul"}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, ContactTag.objects.get(id=item["id"]))

    # No `test_list_invalid_filters`: every filter of `ContactTagFilterSchema` is a
    # string, so no value can fail to parse.

    @parameterized.expand(
        [
            ([], ["name", "id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["color"], ["color", "id"]),
            (["-color"], ["-color", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(ContactTag.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    @parameterized.expand(
        [
            (["not_a_field"],),
            (["-not_a_field"],),
            (["id"],),  # not an ordering field of the controller
        ]
    )
    def test_list_invalid_ordering(self, ordering_fields):
        response = self.do_request("GET", self.url, params={"ordering": ",".join(ordering_fields)})

        self.assertEqual(response.status_code, 422)

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], TAG_FIELDS, 5),  # default means all fields
            (["name"], ["id", "name"], 5),  # `id` is always returned
            (["color"], ["id", "color"], 5),
            (["id"], ["id"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_TAG_IDS))
        for item in data["results"]:
            self.assert_api_format(item, ContactTag.objects.get(id=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "name"],),
            (["contacts"],),  # the reverse relation is not published
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("FELLOW", [TAG_ID1]),  # case insensitive
            ("i", [TAG_ID1, TAG_ID2, TAG_ID3]),
            ("Nazgul", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, ContactTag.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contacttag.read"], 200),
            (["totem.contacttag.create", "totem.contacttag.update", "totem.contacttag.delete"], 403),
            (["totem.contact.read"], 403),
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
            (["totem.contacttag.read"], 200),
            (["totem.contacttag.create", "totem.contacttag.update", "totem.contacttag.delete"], 403),
            (["totem.contact.read"], 403),
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
        self.assert_api_format(response.json(), self.tag_hobbit)

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{TAG_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contacttag.read"], 200),
            (["totem.contacttag.create", "totem.contacttag.update", "totem.contacttag.delete"], 403),
            (["totem.contact.read"], 403),
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
            (["totem.contacttag.read"], 200),
            (["totem.contacttag.create", "totem.contacttag.update", "totem.contacttag.delete"], 403),
            (["totem.contact.read"], 403),
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
            ({"name": "Hobbit"}, 422, "__all__"),  # the name is unique
            ({"name": "hobbit"}, 422, "__all__"),  # ... whatever the case
            ({"color": None}, 422, "color"),
            ({"color": -1}, 422, "color"),
            ({"color": 16}, 422, "color"),
            ({"color": 0}, 201, None),
            ({"color": 15}, 201, None),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_defaults_the_color(self):
        response = self.do_request("POST", self.url, data={"name": "Ranger"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["color"], 0)

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, ContactTag.objects.get(id=data["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contacttag.create"], 201),
            (["totem.contacttag.read", "totem.contacttag.update", "totem.contacttag.delete"], 403),
            (["totem.contact.create"], 403),
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
            (["totem.contacttag.create"], 201),
            (["totem.contacttag.read", "totem.contacttag.update", "totem.contacttag.delete"], 403),
            (["totem.contact.create"], 403),
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
            ({"name": None}, 422, "name"),
            ({"name": "Fellowship"}, 422, "__all__"),  # taken by another tag
            ({"name": "FELLOWSHIP"}, 422, "__all__"),  # ... whatever the case
            ({"name": "Hobbit"}, 200, None),  # its own name
            ({"name": "HOBBIT"}, 200, None),  # its own name, recased
            ({"color": None}, 422, "color"),
            ({"color": -1}, 422, "color"),
            ({"color": 16}, 422, "color"),
            ({"color": 15}, 200, None),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), ContactTag.objects.get(pk=TAG_ID2))
        self.assertEqual(ContactTag.objects.get(pk=TAG_ID2).name, "Halfling")

    def test_update_keeps_the_contacts(self):
        # Renaming a tag renames it on every contact: the relation is by id.
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(Contact.objects.filter(tags=TAG_ID2).values_list("pk", flat=True)), [CONTACT_ID1]
        )

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{TAG_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contacttag.update"], 200),
            (["totem.contacttag.create", "totem.contacttag.read", "totem.contacttag.delete"], 403),
            (["totem.contact.update"], 403),
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
            (["totem.contacttag.update"], 200),
            (["totem.contacttag.create", "totem.contacttag.read", "totem.contacttag.delete"], 403),
            (["totem.contact.update"], 403),
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
        # Wizard is on no contact.
        response = self.do_request("DELETE", f"{self.url}{TAG_ID3}/")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(ContactTag.objects.filter(pk=TAG_ID3).exists())

    def test_delete_a_tag_in_use(self):
        # A tag on contacts is deleted all the same: the many-to-many rows go with
        # it, and the contacts simply lose the tag. Nothing protects it.
        response = self.do_request("DELETE", f"{self.url}{TAG_ID1}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(ContactTag.objects.filter(pk=TAG_ID1).exists())
        self.assertTrue(Contact.objects.filter(pk__in=[CONTACT_ID1, CONTACT_ID2]).count() == 2)
        self.assertEqual(
            sorted(Contact.objects.get(pk=CONTACT_ID1).tags.values_list("pk", flat=True)), [TAG_ID2]
        )
        self.assertFalse(Contact.objects.get(pk=CONTACT_ID2).tags.exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{TAG_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contacttag.delete"], 204),
            (["totem.contacttag.create", "totem.contacttag.read", "totem.contacttag.update"], 403),
            (["totem.contact.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", f"{self.url}{TAG_ID3}/")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(ContactTag.objects.filter(pk=TAG_ID3).exists(), status_code != 204)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contacttag.delete"], 204),
            (["totem.contacttag.create", "totem.contacttag.read", "totem.contacttag.update"], 403),
            (["totem.contact.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", f"{self.url}{TAG_ID3}/", auth="apikey")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(ContactTag.objects.filter(pk=TAG_ID3).exists(), status_code != 204)
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
        fields = fields or TAG_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], obj.pk)
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "color" in fields:
            self.assertEqual(api_data["color"], obj.color)

        self.assertEqual(set(fields), set(api_data))
