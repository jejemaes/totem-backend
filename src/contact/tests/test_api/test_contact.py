from unittest.mock import patch

from django.test import TestCase
from django.utils.dateparse import parse_datetime
from parameterized import parameterized

from authentication.testing import mint_access_token
from contact.models import Contact
from contact.services import ContactService
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    CONTACT_ID1,
    CONTACT_ID2,
    CONTACT_ID3,
    CONTACT_SCOPES,
    PERMISSION_DENIED,
    TAG_ID1,
    TAG_ID2,
    TAG_ID3,
    CommonTestMixin,
)

CONTACT_ID4 = "01ARZ3NDEKTSV4RRFFQ69G5FAV"  # matches no contact

ALL_CONTACT_IDS = [CONTACT_ID1, CONTACT_ID2, CONTACT_ID3]

CONTACT_FIELDS = [
    "id",
    "first_name",
    "last_name",
    "email",
    "mobile",
    "birth_date",
    "number",
    "street",
    "zip",
    "city",
    "country",
    "tags",
    "create_date",
    "update_date",
]


class ContactAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The contacts, through the whole CRUD.

    No `*_access_rules` tests: no `BaseRule` is registered for `Contact`, so there
    is no rule a role could hold to narrow them. Add them with the first one.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = CONTACT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/contacts/"
        cls.url_detail = f"/api/v1/contacts/{CONTACT_ID1}/"
        cls.payload_create = {
            "first_name": "Gandalf",
            "last_name": "Mithrandir",
            "email": "gandalf@istari.com",
            "mobile": "+32 470 00 00 07",
            "number": "1",
            "street": "Orthanc",
            "zip": "7777",
            "city": "Isengard",
            "country": "GD",
            "tags": [TAG_ID3],
        }
        cls.payload_update = {
            "first_name": "Samsagace",
            "email": "samsagace@lacomte.com",
            "city": "Bag End",
            "country": "GD",
            "tags": [TAG_ID2],
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_CONTACT_IDS))
        # Default ordering is by last name, then first name.
        self.assertEqual([item["id"] for item in data["results"]], [CONTACT_ID2, CONTACT_ID1, CONTACT_ID3])

        for item in data["results"]:
            self.assert_api_format(item, Contact.objects.get(pk=item["id"]))

    def test_list_serializes_relations_as_nested_objects(self):
        response = self.do_request("GET", self.url, params={"search": "gamegie"})
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        # The country goes out under `id`, which is its ISO code.
        self.assertEqual(item["country"], {"id": "SH", "name": "The Shire"})
        self.assertCountEqual(
            item["tags"],
            [{"id": TAG_ID1, "name": "Fellowship", "color": 3}, {"id": TAG_ID2, "name": "Hobbit", "color": 5}],
        )

    def test_list_keeps_a_null_relation(self):
        # Bilbon has no country and no tag: the keys stay, as `null` and `[]`.
        response = self.do_request("GET", self.url, params={"search": "sacquet"})
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(item["country"])
        self.assertEqual(item["tags"], [])

    def test_list_exposes_the_timestamps(self):
        response = self.do_request("GET", self.url, params={"search": "gamegie"})
        item = response.json()["results"][0]

        self.assertIsNotNone(item["create_date"])
        self.assertIsNotNone(item["update_date"])

    @parameterized.expand(
        [
            ({"email": "gondor"}, [CONTACT_ID2]),
            ({"email": ".com"}, [CONTACT_ID1, CONTACT_ID2]),
            ({"city": "minas"}, [CONTACT_ID2]),
            ({"city": "rivendell"}, []),
            ({"country": "SH"}, [CONTACT_ID1]),
            ({"country": "MO"}, []),
            ({"tag": TAG_ID1}, [CONTACT_ID1, CONTACT_ID2]),
            ({"tag": TAG_ID2}, [CONTACT_ID1]),
            ({"tag": TAG_ID3}, []),  # a tag nobody carries
            # Filters combine with AND.
            ({"tag": TAG_ID1, "country": "GD"}, [CONTACT_ID2]),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, Contact.objects.get(pk=item["id"]))

    # `tag` is the only filter that can fail to parse: the others are strings.
    @parameterized.expand(
        [
            ({"tag": "not-a-ulid"}, "tag"),
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["last_name", "first_name", "id"]),  # default
            (["last_name"], ["last_name", "id"]),
            (["-last_name"], ["-last_name", "id"]),
            (["first_name"], ["first_name", "id"]),
            (["email"], ["email", "id"]),
            (["city"], ["city", "id"]),
            (["birth_date"], ["birth_date", "id"]),
            (["create_date"], ["create_date", "id"]),
            (["-create_date"], ["-create_date", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(Contact.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    @parameterized.expand(
        [
            (["country__name"],),  # a related lookup is not an ordering field
            (["mobile"],),  # a field not listed in `list_ordering_fields`
        ]
    )
    def test_list_invalid_ordering(self, ordering_fields):
        response = self.do_request("GET", self.url, params={"ordering": ",".join(ordering_fields)})

        self.assertEqual(response.status_code, 422)

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], CONTACT_FIELDS, 7),  # default means all fields: country and tags prefetched
            (["last_name"], ["id", "last_name"], 5),  # `id` is always returned
            (["last_name", "email", "city"], ["id", "last_name", "email", "city"], 5),
            (["country"], ["id", "country"], 6),
            (["tags"], ["id", "tags"], 6),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_CONTACT_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Contact.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "tags"],),  # with a relation
            (["not_existing_field", "last_name"],),
            (["country_id"],),  # the column of a relation is not a public token
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("gamegie", [CONTACT_ID1]),  # the last name
            ("ARAGORN", [CONTACT_ID2]),  # the first name, case insensitive
            ("gondor.com", [CONTACT_ID2]),  # the email
            ("a", ALL_CONTACT_IDS),
            ("hobbiton", []),  # the city is not searched
            ("sauron", []),
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
            (["totem.contact.read"], 200),
            (["totem.contact.create", "totem.contact.update", "totem.contact.delete"], 403),
            (["totem.contacttag.read"], 403),
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
            (["totem.contact.read"], 200),
            (["totem.contact.create", "totem.contact.update", "totem.contact.delete"], 403),
            (["totem.contacttag.read"], 403),
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
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(data["id"]), 26)  # a ULID
        self.assert_api_format(data, Contact.objects.get(pk=CONTACT_ID1))

    def test_retrieve_response_without_relations(self):
        response = self.do_request("GET", f"/api/v1/contacts/{CONTACT_ID3}/")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(data["country"])
        self.assertEqual(data["tags"], [])
        self.assertEqual(data["birth_date"], "2890-09-22")
        self.assert_api_format(data, Contact.objects.get(pk=CONTACT_ID3))

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"/api/v1/contacts/{CONTACT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.read"], 200),
            (["totem.contact.create", "totem.contact.update", "totem.contact.delete"], 403),
            (["totem.contacttag.read"], 403),
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
            (["totem.contact.read"], 200),
            (["totem.contact.create", "totem.contact.update", "totem.contact.delete"], 403),
            (["totem.contacttag.read"], 403),
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
            # Every field is optional on the model: a contact may be a bare name.
            ({"first_name": None}, 201, None),
            ({"email": None}, 201, None),
            ({"country": None}, 201, None),
            ({"tags": []}, 201, None),
            ({"birth_date": "2968-09-22"}, 201, None),
            ({"email": "not an email"}, 422, "email"),
            ({"birth_date": "not a date"}, 422, "birth_date"),
            ({"country": "ZZ"}, 422, "country"),  # an unknown country
            ({"tags": ["01ARZ3NDEKTSV4RRFFQ69G5FAV"]}, 422, "tags"),  # an unknown tag
            ({"tags": ["not-a-ulid"]}, 422, "tags"),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code, response.content)
        if status_code == 422:
            self.assertIn(error_field, str(response.json()))
            self.assertFalse(Contact.objects.filter(last_name="Mithrandir").exists())

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(len(data["id"]), 26)
        self.assertEqual(data["country"], {"id": "GD", "name": "Gondor"})
        self.assertEqual(data["number"], "1")

        contact = Contact.objects.get(pk=data["id"])
        self.assertEqual(contact.country_id, "GD")
        self.assertEqual([tag.pk for tag in contact.tags.all()], [TAG_ID3])
        self.assert_api_format(data, contact)

    def test_create_without_a_country(self):
        # First nullable foreign key of the project: `create` builds its values
        # with `exclude_unset=False`, so the unset relation reaches the resolution
        # loop as None and must not be read as an invalid one.
        response = self.do_request("POST", self.url, data={"last_name": "Radagast"})
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertIsNone(data["country"])
        self.assertEqual(data["tags"], [])

    def test_create_responds_with_what_the_database_holds(self):
        """The response is refetched, not the instance as built: a value the
        database holds by the end of the write -- here changed by a postprocess,
        relation included -- is what the client gets back."""
        def postprocess(service, instances):
            Contact.objects.filter(pk__in=[i.pk for i in instances]).update(city="Valinor")
            for instance in instances:
                instance.tags.add(TAG_ID1)
            return instances

        with patch.object(ContactService, "_create_postprocess", postprocess):
            response = self.do_request("POST", self.url, data={"last_name": "Mithrandir", "city": "Isengard"})
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(data["city"], "Valinor")
        self.assertEqual([tag["id"] for tag in data["tags"]], [TAG_ID1])

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.create"], 201),
            (["totem.contact.read", "totem.contact.update", "totem.contact.delete"], 403),
            (["totem.contacttag.create"], 403),
        ]
    )
    def test_create_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Contact.objects.filter(last_name="Mithrandir").exists(), status_code == 201)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.create"], 201),
            (["totem.contact.read", "totem.contact.update", "totem.contact.delete"], 403),
            (["totem.contacttag.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Contact.objects.filter(last_name="Mithrandir").exists(), status_code == 201)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"first_name": None}, 200, None),
            ({"country": None}, 200, None),  # unsets the country
            ({"tags": []}, 200, None),  # removes every tag
            ({"email": "not an email"}, 422, "email"),
            ({"birth_date": "not a date"}, 422, "birth_date"),
            ({"country": "ZZ"}, 422, "country"),
            ({"tags": ["01ARZ3NDEKTSV4RRFFQ69G5FAV"]}, 422, "tags"),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code, response.content)
        if status_code == 422:
            self.assertIn(error_field, str(response.json()))
            # Nothing of the payload was written.
            self.assertEqual(Contact.objects.get(pk=CONTACT_ID1).first_name, "Sam")

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200, data)
        contact = Contact.objects.get(pk=CONTACT_ID1)
        self.assertEqual(contact.first_name, "Samsagace")
        self.assertEqual(contact.country_id, "GD")
        # `tags` replaces the set, it does not add to it.
        self.assertEqual([tag.pk for tag in contact.tags.all()], [TAG_ID2])
        self.assert_api_format(data, contact)

    def test_update_moves_update_date(self):
        before = Contact.objects.get(pk=CONTACT_ID1)

        response = self.do_request("PATCH", self.url_detail, data={"city": "Bywater"})

        self.assertEqual(response.status_code, 200, response.json())
        after = Contact.objects.get(pk=CONTACT_ID1)
        self.assertEqual(after.city, "Bywater")
        self.assertEqual(after.create_date, before.create_date)
        # `queryset.update()` does not run `auto_now`; `ContactQuerySet` does.
        self.assertGreater(after.update_date, before.update_date)

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"/api/v1/contacts/{CONTACT_ID4}/", data={"city": "Bywater"})

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.update"], 200),
            (["totem.contact.create", "totem.contact.read", "totem.contact.delete"], 403),
            (["totem.contacttag.update"], 403),
        ]
    )
    def test_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Contact.objects.get(pk=CONTACT_ID1).first_name == "Samsagace", status_code == 200)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.update"], 200),
            (["totem.contact.create", "totem.contact.read", "totem.contact.delete"], 403),
            (["totem.contacttag.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Contact.objects.get(pk=CONTACT_ID1).first_name == "Samsagace", status_code == 200)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Contact.objects.filter(pk=CONTACT_ID1).exists())
        # The tags themselves stay: only the relation rows go.
        self.assertEqual(Contact.tags.through.objects.filter(contact_id=CONTACT_ID1).count(), 0)
        self.assertTrue(Contact.tags.field.related_model.objects.filter(pk__in=[TAG_ID1, TAG_ID2]).count() == 2)

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"/api/v1/contacts/{CONTACT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.delete"], 204),
            (["totem.contact.create", "totem.contact.read", "totem.contact.update"], 403),
            (["totem.contacttag.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Contact.objects.filter(pk=CONTACT_ID1).exists(), status_code != 204)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.contact.delete"], 204),
            (["totem.contact.create", "totem.contact.read", "totem.contact.update"], 403),
            (["totem.contacttag.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Contact.objects.filter(pk=CONTACT_ID1).exists(), status_code != 204)
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
        fields = fields or CONTACT_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], obj.pk)
        for name in ["first_name", "last_name", "email", "mobile", "number", "street", "zip", "city"]:
            if name in fields:
                self.assertEqual(api_data[name], getattr(obj, name))
        if "birth_date" in fields:
            self.assertEqual(api_data["birth_date"], obj.birth_date.isoformat() if obj.birth_date else None)
        if "country" in fields:
            self.assertEqual(
                api_data["country"],
                {"id": obj.country.code, "name": obj.country.name} if obj.country else None,
            )
        if "tags" in fields:
            self.assertCountEqual(
                api_data["tags"],
                [{"id": tag.pk, "name": tag.name, "color": tag.color} for tag in obj.tags.all()],
            )
        for name in ["create_date", "update_date"]:
            if name in fields:
                # Serialized to the millisecond, stored to the microsecond.
                value = getattr(obj, name)
                self.assertEqual(
                    parse_datetime(api_data[name]),
                    value.replace(microsecond=value.microsecond // 1000 * 1000),
                )

        self.assertEqual(set(fields), set(api_data))
