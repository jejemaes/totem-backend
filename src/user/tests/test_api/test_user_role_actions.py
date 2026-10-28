from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_policy import access_policy
from user.access_rights import get_all_permission, get_user_scopes

from .common import CommonTestMixin

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class UserRoleActionsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `/user-roles/permissions/` and `/user-roles/access-rules/`: the registries a
    role is built from, so what a role editor offers to pick from. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = ["totem.userrole.read"]
        cls.role.rules = []
        cls.role.save()

        cls.url_permissions = "/api/v1/user-roles/permissions/"
        cls.url_access_rules = "/api/v1/user-roles/access-rules/"

    # ------------------------------------------
    # Permissions Read
    # ------------------------------------------

    def test_permissions_read_response(self):
        response = self.do_request("GET", self.url_permissions)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"id": permission, "name": name} for permission, name in get_all_permission()],
        )

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.read", "totem.user.update"], 403),
        ]
    )
    def test_permissions_read_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_permissions)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.read", "totem.user.update"], 403),
        ]
    )
    def test_permissions_read_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_permissions, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Access Rules Read
    # ------------------------------------------

    def test_access_rules_read_response(self):
        response = self.do_request("GET", self.url_access_rules)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"id": rule.identifier, "name": rule.name, "description": rule.description}
                for rule in access_policy.get_all_rules()
            ],
        )

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.read", "totem.user.update"], 403),
        ]
    )
    def test_access_rules_read_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_access_rules)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.read", "totem.user.update"], 403),
        ]
    )
    def test_access_rules_read_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_access_rules, auth="apikey")

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
