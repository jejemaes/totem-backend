from django.test import TestCase
from parameterized import parameterized

from base.models import Country
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin


class CountryDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Country.objects.bulk_create([
            Country(code="BE", name="Belgium"),
            Country(code="FR", name="France"),
        ])
        cls.url = "/api/v1/countries/display-name/"

    def test_response(self):
        # The code is the pk, exposed as `id`; an unknown code is absent.
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params={"id": "FR,XX,BE"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": "FR", "name": "France"}, {"id": "BE", "name": "Belgium"}])

    @parameterized.expand([("totem.country.read", 200), ("totem.contact.read", 403)])
    def test_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params={"id": "BE"})

        self.assertEqual(response.status_code, status_code)
