from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.models import UserRole

from .common import CommonTestMixin

ROLE_ID_BASE = "TEST_BASEUSER"  # the role of `CommonTestMixin`, held by Frodon
ROLE_ID1 = "FELLOWSHIP"
ROLE_ID2 = "ELROND_COUNCIL"
ROLE_ID3 = "SHIRE_HOBBITS"
ROLE_ID4 = "MORDOR_ORCS"

ALL_ROLE_IDS = [ROLE_ID_BASE, ROLE_ID1, ROLE_ID2, ROLE_ID3, ROLE_ID4]

ROLE_FIELDS = ["id", "name", "permissions", "rules"]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


@freeze_time("2024-11-18 11:12:13")
class UserRoleAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The user role API publishes a list only.

    No `*_access_rules` tests: no `BaseRule` is registered for `UserRole`, so there
    is no rule a role could hold to narrow them. Add them with the first one.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        UserRole.objects.bulk_create(
            [
                UserRole(
                    id=ROLE_ID1,
                    name="Fellowship of the Ring",
                    permissions=["totem.user.read"],
                    rules=["user_manage_all_user"],
                ),
                UserRole(id=ROLE_ID2, name="Council of Elrond"),
                UserRole(id=ROLE_ID3, name="Shire Hobbits", rules=["user_manage_own_profile"]),
                UserRole(id=ROLE_ID4, name="Mordor Orcs"),
            ]
        )

        # Frodon holds the base role only: a second one would add its permissions
        # and its rules to the ones the access tests set.
        cls.role.permissions = ["totem.userrole.read"]
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/user-roles/"

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_ROLE_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_ROLE_IDS))

        for item in data["results"]:
            self.assert_api_format(item, UserRole.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            # `name` is an exact match, unlike `search`.
            ({"name": "Mordor Orcs"}, [ROLE_ID4]),
            ({"name": "mordor"}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, UserRole.objects.get(id=item["id"]))

    # No `test_list_invalid_filters`: every filter of `UserRoleFilterSchema` is a
    # string, so no value can fail to parse.

    @parameterized.expand(
        [
            ([], ["id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["id"], ["id"]),
            (["-id"], ["-id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            list(UserRole.objects.order_by(*order_by).values_list("pk", flat=True)),
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], ROLE_FIELDS, 5),  # default means all fields
            (["name"], ["id", "name"], 5),  # `id` is always returned
            (["rules", "name"], ["id", "rules", "name"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_ROLE_IDS))
        for item in data["results"]:
            self.assert_api_format(item, UserRole.objects.get(id=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "name"],),
            (["users"],),  # a relation of the model the schema does not publish
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("of", [ROLE_ID1, ROLE_ID2]),
            ("HOBBIT", [ROLE_ID3]),  # case insensitive
            ("rohan", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, UserRole.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.userrole.read"], 200),
            (["totem.user.create", "totem.user.read", "totem.user.update", "totem.user.delete"], 403),
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
            (["totem.userrole.read"], 200),
            (["totem.user.create", "totem.user.read", "totem.user.update", "totem.user.delete"], 403),
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
        fields = fields or ROLE_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], obj.id)
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "permissions" in fields:
            self.assertEqual(api_data["permissions"], obj.permissions)
        if "rules" in fields:
            self.assertEqual(api_data["rules"], obj.rules)

        self.assertEqual(set(fields), set(api_data))
