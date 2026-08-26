import json

from django.test import TestCase
from parameterized import parameterized

from base.models import Country
from contact.models import Contact, ContactTag
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin

ALL_SCOPES = (
    "totem.contact.create totem.contact.read "
    "totem.contact.update totem.contact.delete"
)


class ContactAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.country = Country.objects.create(code="BE", name="Belgium")
        cls.tag_vip = ContactTag.objects.create(name="VIP", color=3)
        cls.tag_family = ContactTag.objects.create(name="Family", color=5)

        cls.tournesol = Contact.objects.create(
            last_name="Tournesol", first_name="Tryphon",
            email="tryphon@moulinsart.be", city="Moulinsart", country=cls.country,
        )
        cls.tournesol.tags.set([cls.tag_vip])
        cls.haddock = Contact.objects.create(
            last_name="Haddock", first_name="Archibald", email="archibald@moulinsart.be",
        )

        cls.user_access_token_frodon.scope = ALL_SCOPES
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/contacts/"

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
        self.assertEqual(data["count"], 2)
        # Default ordering is by last name, then first name.
        self.assertEqual(
            [item["last_name"] for item in data["results"]], ["Haddock", "Tournesol"]
        )

    def test_list_serializes_relations_as_nested_objects(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"search": "tournesol"}
        )
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        # The country goes out under `id`, which is its ISO code.
        self.assertEqual(item["country"], {"id": "BE", "name": "Belgium"})
        self.assertEqual(
            item["tags"], [{"id": self.tag_vip.pk, "name": "VIP", "color": 3}]
        )

    def test_list_exposes_the_timestamps(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"search": "tournesol"}
        )
        item = response.json()["results"][0]

        self.assertIsNotNone(item["create_date"])
        self.assertIsNotNone(item["update_date"])

    @parameterized.expand([
        ({"search": "tournesol"}, ["Tournesol"]),
        ({"search": "archibald"}, ["Haddock"]),
        ({"search": "moulinsart.be"}, ["Haddock", "Tournesol"]),
        ({"city": "moulin"}, ["Tournesol"]),
        ({"country": "BE"}, ["Tournesol"]),
        ({"country": "FR"}, []),
    ])
    def test_list_filters(self, filters, expected):
        response = self.do_api_request(self.url, "GET", self.token, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["last_name"] for item in data["results"]], expected)

    def test_list_filter_by_tag(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"tag": self.tag_vip.pk}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["last_name"] for item in response.json()["results"]], ["Tournesol"]
        )

    @parameterized.expand([
        ("last_name", ["Haddock", "Tournesol"]),
        ("-last_name", ["Tournesol", "Haddock"]),
        ("create_date", ["Tournesol", "Haddock"]),
        ("-create_date", ["Haddock", "Tournesol"]),
    ])
    def test_list_ordering(self, ordering, expected):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"ordering": ordering}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["last_name"] for item in response.json()["results"]], expected
        )

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(
            f"{self.url}{self.tournesol.pk}/", "GET", self.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["id"], self.tournesol.pk)
        self.assertEqual(len(data["id"]), 26)
        self.assertEqual(data["last_name"], "Tournesol")

    def test_retrieve_unknown(self):
        response = self.do_api_request(
            f"{self.url}01ARZ3NDEKTSV4RRFFQ69G5FAV/", "GET", self.token
        )

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    def test_create(self):
        payload = {
            "last_name": "Castafiore",
            "first_name": "Bianca",
            "email": "bianca@milan.it",
            "number": "12A",
            "street": "Via Roma",
            "zip": "1000",
            "city": "Milano",
            "country": "BE",
            "tags": [self.tag_family.pk],
        }

        response = self.do_api_request(
            self.url, "POST", self.token, data=json.dumps(payload)
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(len(data["id"]), 26)
        self.assertEqual(data["country"], {"id": "BE", "name": "Belgium"})
        self.assertEqual(data["number"], "12A")

        contact = Contact.objects.get(pk=data["id"])
        self.assertEqual(contact.country, self.country)
        self.assertEqual([t.pk for t in contact.tags.all()], [self.tag_family.pk])

    def test_create_with_unknown_country(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({"last_name": "Castafiore", "country": "ZZ"}),
        )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Contact.objects.filter(last_name="Castafiore").exists())

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    def test_update_moves_update_date(self):
        before = Contact.objects.get(pk=self.tournesol.pk)

        response = self.do_api_request(
            f"{self.url}{self.tournesol.pk}/", "PATCH", self.token,
            data=json.dumps({"city": "Bruxelles"}),
        )

        self.assertEqual(response.status_code, 200, response.json())
        after = Contact.objects.get(pk=self.tournesol.pk)
        self.assertEqual(after.city, "Bruxelles")
        self.assertEqual(after.create_date, before.create_date)
        # `queryset.update()` does not run `auto_now`; `ContactQuerySet` does.
        self.assertGreater(after.update_date, before.update_date)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete(self):
        response = self.do_api_request(
            f"{self.url}{self.haddock.pk}/", "DELETE", self.token
        )

        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(Contact.objects.filter(pk=self.haddock.pk).exists())

    # ------------------------------------------
    # Permissions
    # ------------------------------------------

    @parameterized.expand([
        ("GET", "totem.contact.create"),
        ("POST", "totem.contact.read"),
        ("PATCH", "totem.contact.read"),
        ("DELETE", "totem.contact.read"),
    ])
    def test_operation_requires_its_own_scope(self, method, wrong_scope):
        self.user_access_token_frodon.scope = wrong_scope
        self.user_access_token_frodon.save()
        url = self.url if method in ("GET", "POST") else f"{self.url}{self.haddock.pk}/"
        # A valid body: ninja validates it before the view runs, so an empty one
        # would answer 422 without ever reaching the permission check.
        body = json.dumps({"last_name": "Nope"})

        response = self.do_api_request(url, method, self.token, data=body)

        self.assertEqual(response.status_code, 403)

    # ------------------------------------------
    # Regression guards on the shared API layer
    # ------------------------------------------

    def test_list_keeps_a_null_relation(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"search": "haddock"}
        )
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(item["country"])

    def test_create_without_a_country(self):
        # First nullable foreign key of the project: `create` builds its values
        # with `exclude_unset=False`, so the unset relation reaches the resolution
        # loop as None and must not be read as an invalid one.
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({"last_name": "Castafiore"}),
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertIsNone(data["country"])
        self.assertEqual(data["tags"], [])
