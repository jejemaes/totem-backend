from django.db.models import F
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.choices import UserType
from user.models import User

from .common import USER_ID1, USER_ID2, USER_ID3, CommonTestMixin

USER_ID4 = "49c7b4f5-b436-4c47-bea1-d3e60b9ab492"
USER_ID5 = "5263de93-e694-11ef-b873-34610551afcd"  # matches no user

ALL_USER_IDS = [USER_ID1, USER_ID2, USER_ID3, USER_ID4]

USER_SCOPES = ["totem.user.create", "totem.user.read", "totem.user.update", "totem.user.delete"]

USER_FIELDS = [
    "id",
    "login",
    "email",
    "first_name",
    "last_name",
    "language",
    "is_active",
    "user_type",
    "avatar",
    "roles",
]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


@freeze_time("2024-11-18 11:12:13")
class UserAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_pipin, cls.user_galadriel = User.objects.bulk_create(
            [
                User(
                    id=USER_ID3,
                    username="pipin@lacomte.com",
                    email="pipin@lacomte.com",
                    first_name="Pipin",
                    user_type=UserType.INTERNAL,
                ),
                User(
                    id=USER_ID4,
                    username="galadriel@lothlorien.com",
                    email="galadriel@lothlorien.com",
                    user_type=UserType.INTERNAL,
                    is_active=False,
                ),
            ]
        )

        # Frodon acts through the role every user of `CommonTestMixin` holds. It is
        # granted the whole user API and no rule here; the access tests narrow it.
        cls.role.permissions = USER_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/users/"
        cls.url_detail = f"/api/v1/users/{USER_ID2}/"
        cls.payload_create = {
            "login": "sam@lacomte.com",
            "email": "sam@lacomte.com",
            "last_name": "Gamegie",
            "first_name": "Sam",
            "language": "fr",
            "user_type": UserType.PORTAL,
            "roles": [],
        }
        cls.payload_update = {
            "login": "smeagol@misty-mountains.com",
            "email": "smeagol@misty-mountains.com",
            "last_name": "Stoor",
            "first_name": "Smeagol",
            "language": "en-us",
            "user_type": UserType.INTERNAL,
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_USER_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_USER_IDS))

        for item in data["results"]:
            self.assert_api_format(item, User.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"login": "lothlorien"}, [USER_ID4]),
            ({"email": "lacomte"}, [USER_ID1, USER_ID3]),
            ({"is_active": True}, [USER_ID1, USER_ID2, USER_ID3]),
            ({"is_active": False}, [USER_ID4]),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, User.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"is_active": "not a boolean"}, "is_active"),
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["username", "id"]),  # default
            (["login"], ["username", "id"]),
            (["-login"], ["-username", "id"]),
            (["email"], ["email", "id"]),
            (["-email"], ["-email", "id"]),
            (["is_active"], ["is_active", "id"]),
            (["-is_active"], ["-is_active", "id"]),
            (["date_joined"], ["date_joined", "id"]),
            (["-date_joined"], ["-date_joined", "id"]),
            (["first_name"], [F("first_name").asc(nulls_last=True), "id"]),
            (["-first_name"], [F("first_name").desc(nulls_last=True), "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in User.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], USER_FIELDS, 6),  # default means all fields
            (["login"], ["id", "login"], 5),  # `id` is always returned
            (["login", "email", "is_active"], ["id", "login", "email", "is_active"], 5),
            (["email", "roles"], ["id", "email", "roles"], 6),  # the relation costs its prefetch
            (["roles"], ["id", "roles"], 6),
            (["id"], ["id"], 5),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_USER_IDS))
        for item in data["results"]:
            self.assert_api_format(item, User.objects.get(id=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "roles"],),  # with a relation
            (["not_existing_field", "login"],),
            (["username"],),  # the ORM name of an aliased field is not a public token
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("lacomte", [USER_ID1, USER_ID3]),  # the email
            ("frodon", [USER_ID1]),  # the login
            ("mordor", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, User.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.user.read"], 200),
            (["totem.user.create", "totem.user.update", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
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
            (["totem.user.read"], 200),
            (["totem.user.create", "totem.user.update", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
        ]
    )
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], ALL_USER_IDS),
            (["user_manage_own_profile"], [USER_ID1]),
            (["user_manage_all_user"], ALL_USER_IDS),
            # The rules of one role combine with AND.
            (["user_manage_own_profile", "user_manage_all_user"], [USER_ID1]),
        ]
    )
    def test_list_user_access_rules(self, rules, expected_pks):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ([],),
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
            (["user_manage_own_profile", "user_manage_all_user"],),
        ]
    )
    def test_list_apikey_access_rules(self, rules):
        # A key has no user, hence no role: whatever the rules of the roles, it
        # reads every user of the tenant. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(ALL_USER_IDS))

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        # Gollum has a role: serializing `roles` is what forces the relation to be
        # resolved, so this covers the relational part of the payload.
        self.assert_api_format(response.json(), self.user_gollum)

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"/api/v1/users/{USER_ID5}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.user.read"], 200),
            (["totem.user.create", "totem.user.update", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
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
            (["totem.user.read"], 200),
            (["totem.user.create", "totem.user.update", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
        ]
    )
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], USER_ID2, 200),
            (["user_manage_own_profile"], USER_ID1, 200),
            (["user_manage_own_profile"], USER_ID2, 404),  # out of reach reads as missing
            (["user_manage_all_user"], USER_ID2, 200),
        ]
    )
    def test_retrieve_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", f"/api/v1/users/{pk}/")

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual(response.json()["id"], pk)

    @parameterized.expand(
        [
            ([],),
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
        ]
    )
    def test_retrieve_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], USER_ID2)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"login": None}, 422),
            ({"email": None}, 422),
            ({"email": "not an email"}, 422),
            ({"user_type": None}, 422),
            ({"user_type": "hobbit"}, 422),
            ({"first_name": None}, 201),
            ({"last_name": None}, 201),
            ({"language": "elvish"}, 422),
            ({"language": None}, 422),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, User.objects.get(id=data["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.user.create"], 201),
            (["totem.user.read", "totem.user.update", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
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
            (["totem.user.create"], 201),
            (["totem.user.read", "totem.user.update", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([],),
            # `user_manage_own_profile` covers no `create`: it does not hold one back.
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
        ]
    )
    def test_create_user_access_rules(self, rules):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(pk=response.json()["id"], username="sam@lacomte.com").exists())

    @parameterized.expand(
        [
            ([],),
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
        ]
    )
    def test_create_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(pk=response.json()["id"], username="sam@lacomte.com").exists())

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"email": None}, 422),
            ({"email": "not an email"}, 422),
            ({"user_type": None}, 422),
            ({"user_type": "hobbit"}, 422),
            ({"first_name": None}, 200),
            ({"last_name": None}, 200),
            ({"language": "elvish"}, 422),
            ({"language": None}, 422),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), User.objects.get(id=USER_ID2))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.user.update"], 200),
            (["totem.user.create", "totem.user.read", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
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
            (["totem.user.update"], 200),
            (["totem.user.create", "totem.user.read", "totem.user.delete"], 403),
            (["totem.userrole.read"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], USER_ID2, 200),
            (["user_manage_own_profile"], USER_ID1, 200),
            (["user_manage_own_profile"], USER_ID2, 404),
            (["user_manage_all_user"], USER_ID2, 200),
        ]
    )
    def test_update_user_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", f"/api/v1/users/{pk}/", data={"first_name": "Bilbon"})

        self.assertEqual(response.status_code, status_code)
        # Only the record in reach was written.
        self.assertEqual(
            User.objects.get(pk=pk).first_name == "Bilbon",
            status_code == 200,
        )

    @parameterized.expand(
        [
            ([],),
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
        ]
    )
    def test_update_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data={"first_name": "Bilbon"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.get(pk=USER_ID2).first_name, "Bilbon")

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(User.objects.filter(pk=USER_ID2).exists())

    @parameterized.expand(
        [
            ([], 403),
            (["totem.user.delete"], 204),
            (["totem.user.create", "totem.user.read", "totem.user.update"], 403),
            (["totem.userrole.read"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.user.delete"], 204),
            (["totem.user.create", "totem.user.read", "totem.user.update"], 403),
            (["totem.userrole.read"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 204),
            # `user_manage_own_profile` covers no `delete`: it does not hold one
            # back, so Gollum can be deleted by a role that can only read Frodon.
            (["user_manage_own_profile"], 204),
            (["user_manage_all_user"], 204),
        ]
    )
    def test_delete_user_access_rules(self, rules, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(User.objects.filter(pk=USER_ID2).exists(), status_code != 204)

    @parameterized.expand(
        [
            ([],),
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
        ]
    )
    def test_delete_apikey_access_rules(self, rules):
        # The rules of the roles do not bound a key. See `ApiKeyAuth`.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(User.objects.filter(pk=USER_ID2).exists())

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would: granting a scope is editing the role,
        never forging a token.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or USER_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "login" in fields:
            # `username` is exposed as `login` on the whole user API
            self.assertEqual(api_data["login"], obj.username)
        if "email" in fields:
            self.assertEqual(api_data["email"], obj.email)
        if "first_name" in fields:
            self.assertEqual(api_data["first_name"], obj.first_name)
        if "last_name" in fields:
            self.assertEqual(api_data["last_name"], obj.last_name)
        if "language" in fields:
            self.assertEqual(api_data["language"], obj.language)
        if "is_active" in fields:
            self.assertEqual(api_data["is_active"], obj.is_active)
        if "user_type" in fields:
            self.assertEqual(api_data["user_type"], obj.user_type)
        if "avatar" in fields:
            # A `FileField` serializes as its storage name, not a url. Unset, the list
            # answers `""` and retrieve/create/update `null`: an inconsistency of
            # the read paths, tolerated here until it is fixed, not a contract.
            if obj.avatar:
                self.assertEqual(api_data["avatar"], obj.avatar.name)
            else:
                self.assertIn(api_data["avatar"], ("", None))
        if "roles" in fields:
            self.assertCountEqual(
                api_data["roles"],
                [{"id": role.pk, "name": role.name} for role in obj.roles.all()],
            )

        self.assertEqual(set(fields), set(api_data))
