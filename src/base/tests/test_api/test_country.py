from django.test import TestCase
from parameterized import parameterized

from base.models import Country
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin


class CountryAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        Country.objects.bulk_create([
            Country(code="BE", name="Belgium"),
            Country(code="FR", name="France"),
            Country(code="NL", name="Netherlands"),
        ])

        cls.user_access_token_frodon.scope = "totem.country.read"
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/countries/"

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 3)

        for item in data["results"]:
            self.assertEqual(sorted(item.keys()), ["id", "name"])
            # The ISO code is the primary key, exposed publicly as `id`.
            self.assertEqual(item["name"], Country.objects.get(pk=item["id"]).name)

    def test_list_default_ordering_is_by_name(self):
        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]], ["BE", "FR", "NL"]
        )

    @parameterized.expand([
        ({"name": "belg"}, ["BE"]),
        ({"search": "belg"}, ["BE"]),
        ({"search": "nl"}, ["NL"]),  # matches the code, not the name
        ({"search": "nowhere"}, []),
    ])
    def test_list_filters(self, filters, expected_ids):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in data["results"]], expected_ids)
        self.assertEqual(data["count"], len(expected_ids))

    def test_list_requires_the_scope(self):
        self.user_access_token_frodon.scope = "totem.user.read"
        self.user_access_token_frodon.save()

        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token)

        self.assertEqual(response.status_code, 403)

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(
            f"{self.url}BE/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"id": "BE", "name": "Belgium"})

    def test_retrieve_unknown_code(self):
        response = self.do_api_request(
            f"{self.url}ZZ/", "GET", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------
    # Read-only Operations
    # ------------------------------------------

    @parameterized.expand([("POST",), ("PATCH",), ("DELETE",)])
    def test_write_routes_are_not_registered(self, method):
        url = self.url if method == "POST" else f"{self.url}BE/"

        response = self.do_api_request(
            url, method, self.user_access_token_frodon.token, data={"name": "Nope"}
        )

        self.assertEqual(response.status_code, 405)
