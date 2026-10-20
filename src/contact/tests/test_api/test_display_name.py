from django.test import TestCase
from parameterized import parameterized

from contact.models import ContactTag
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin


class ContactTagDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tag_vip = ContactTag.objects.create(name="VIP", color=3)
        cls.tag_family = ContactTag.objects.create(name="Family", color=5)
        cls.url = "/api/v1/contact-tags/display-name/"

    def test_response(self):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token,
            params={"id": f"{self.tag_family.pk},{self.tag_vip.pk}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"id": self.tag_family.pk, "name": "Family", "color": 5},
                {"id": self.tag_vip.pk, "name": "VIP", "color": 3},
            ],
        )

    @parameterized.expand([("totem.contacttag.read", 200), ("totem.contact.read", 403)])
    def test_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params={"id": str(self.tag_vip.pk)}
        )

        self.assertEqual(response.status_code, status_code)
