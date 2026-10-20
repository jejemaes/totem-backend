from django.test import TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin

from .common import USER_ID1, USER_ID2, CommonTestMixin


class UserDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    def request(self, url, ids):
        return self.do_api_request(url, "GET", self.user_access_token_frodon.token, params={"id": ids})

    def test_users(self):
        # `username` is exposed as `login`, as everywhere else.
        response = self.request("/api/v1/users/display-name/", f"{USER_ID2},{USER_ID1}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"id": USER_ID2, "login": "gollum@precious.com"}, {"id": USER_ID1, "login": "frodon@lacomte.com"}],
        )

    def test_user_roles(self):
        # Not shadowed by a retrieve: the controller has none, only `/permissions/`
        # and `/access-rules/` beside the list.
        response = self.request("/api/v1/user-roles/display-name/", "TEST_BASEUSER,UNKNOWN")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"id": "TEST_BASEUSER", "name": "Role Test (Base)"}])

    def test_users_malformed_uuid(self):
        response = self.request("/api/v1/users/display-name/", f"{USER_ID1},frodon")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])

    @parameterized.expand(
        [
            ("/api/v1/users/", USER_ID1, "totem.user.read", 200),
            ("/api/v1/users/", USER_ID1, "totem.userrole.read", 403),
            ("/api/v1/user-roles/", "TEST_BASEUSER", "totem.userrole.read", 200),
            ("/api/v1/user-roles/", "TEST_BASEUSER", "totem.user.read", 403),
        ]
    )
    def test_access_rights(self, url, pk, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.request(f"{url}display-name/", pk)

        self.assertEqual(response.status_code, status_code)
