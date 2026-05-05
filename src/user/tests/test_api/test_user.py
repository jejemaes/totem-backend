from django.test import TestCase
from django.db.models import F
from freezegun import freeze_time
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.choices import UserType
from user.models import User

from .common import USER_ID1, USER_ID2, USER_ID3, CommonTestMixin

USER_ID4 = "49c7b4f5-b436-4c47-bea1-d3e60b9ab492"
USER_ID5 = "5263de93-e694-11ef-b873-34610551afcd"


@freeze_time("2024-11-18 11:12:13")
class UserAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_pipin = User.objects.create(
            id=USER_ID3,
            username="pipin@lacomte.com",
            email="pipin@lacomte.com",
            first_name="Pipin",
            user_type=UserType.INTERNAL,
        )
        cls.user_galadriel = User.objects.create(
            id=USER_ID4,
            username="galadriel@elfe.com",
            email="galadriel@elfe.com",
            user_type=UserType.INTERNAL,
            is_active=False,
        )

        cls.url = "/api/v1/users/"
        cls.url_detail = f"/api/v1/users/{USER_ID2}/"
        cls.url_profile = "/api/v1/users/me/"
        cls.payload_create = {
            "username": "pipin",
            "email": "pipin@lacomte.com",
            "last_name": "Pipin",
            "first_name": "A Hobbit",
            "language": "fr",
            "user_type": UserType.PORTAL,
            "is_active": True,
            "roles": [],
        }
        cls.payload_update = {
            "username": "pipin",
            "email": "pipin@lacomte.com",
            "last_name": "Pipin",
            "first_name": "A Hobbit",
            "language": "fr",
            "user_type": UserType.PORTAL,
            "is_active": True,
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertEqual(len(data["results"]), 4)
        self.assertEqual(data["count"], 4)

        for item in data["results"]:
            obj = User.objects.get(id=item["id"])
            self._assert_api_format(
                item,
                obj,
                [
                    "id",
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "language",
                    "is_active",
                    "user_type",
                    "avatar",
                    "roles",
                ],
            )

    @parameterized.expand(
        [
            ({"username": "elfe"}, [USER_ID4]),
            ({"email": "lacomte"}, [USER_ID1, USER_ID3]),
            ({"is_active": True}, [USER_ID1, USER_ID2, USER_ID3]),
            ({"is_active": False}, [USER_ID4]),
        ]
    )
    def test_list_filters(self, filters, ids):
        qs = User.objects.filter(pk__in=ids)

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertEqual(len(data["results"]), len(qs))
        self.assertEqual(data["count"], len(qs))

        for item in data["results"]:
            obj = qs.get(id=item["id"])
            self._assert_api_format(
                item,
                obj,
                [
                    "id",
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "language",
                    "is_active",
                    "user_type",
                    "avatar",
                    "roles",
                ],
            )

    @parameterized.expand(
        [
            ({"is_active": "invalid boolean"},),
        ]
    )
    def test_list_invalid_filters(self, filters):
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=filters
        )
        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ([], ["username", "id"]),  # default
            (["username"], ["username", "id"]),
            (["-username"], ["-username", "id"]),
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
        ordering = ",".join(ordering_fields)
        params = {}
        if ordering:
            params = {"ordering": ordering}
        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=params
        )
        data = response.json()

        queryset = User.objects.all().order_by(*order_by)

        for instance, item in zip(queryset, data["results"]):
            self.assertEqual(str(instance.pk), item["id"])

    @parameterized.expand(
        [
            (
                [],
                [
                    "id",
                    "roles",
                    "username",
                    "last_name",
                    "first_name",
                    "email",
                    "is_active",
                    "user_type",
                    "language",
                    "avatar",
                ],
                5,
            ),  # default means all fields
            (["username"], ["id", "username"], 4),
            (
                ["username", "email", "is_active"],
                ["id", "username", "email", "is_active"],
                4,
            ),
            (["email", "roles"], ["id", "email", "roles"], 5),
            (["roles"], ["id", "roles"], 5),
            (["id"], ["id"], 4),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        queryfield = ",".join(query_fields)
        params = {}
        if queryfield:
            params = {"fields": queryfield}

        with self.assertNumQueries(query_count):
            response = self.do_api_request(
                self.url, "GET", self.user_access_token_frodon.token, params=params
            )
            data = response.json()

        self.assertEqual(response.status_code, 200)

        record_map = {
            str(obj.pk): obj
            for obj in User.objects.filter(
                pk__in=[item["id"] for item in data["results"]]
            )
        }
        for item in data["results"]:
            obj = record_map.get(item["id"])
            # id is always in response
            self.assertEqual(set(item), set(received_fields))
            self._assert_api_format(item, obj, received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "roles"],),  # with relation
            (["not_existing_field", "username"],),
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        queryfield = ",".join(query_fields)
        params = {}
        if queryfield:
            params = {"fields": queryfield}

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token, params=params
        )

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("lacomte", [USER_ID1, USER_ID3]),
            ("frodon", [USER_ID1]),
            ("no-match", []),
        ]
    )
    def test_list_searching(self, search_term, ids):
        qs = User.objects.filter(pk__in=ids)

        response = self.do_api_request(
            self.url,
            "GET",
            self.user_access_token_frodon.token,
            params={"search": search_term},
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("count", data)
        self.assertIn("results", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertEqual(len(data["results"]), len(qs))
        self.assertEqual(data["count"], len(qs))

        for item in data["results"]:
            obj = qs.get(pk=item["id"])
            self._assert_api_format(
                item,
                obj,
                [
                    "id",
                    "username",
                    "email",
                    "first_name",
                    "last_name",
                    "language",
                    "is_active",
                    "user_type",
                    "avatar",
                    "roles",
                ],
            )

    @parameterized.expand(
        [
            ("totem.user.create", 403),
            ("totem.user.read", 200),
            ("totem.user.update", 403),
            ("totem.user.delete", 403),
        ]
    )
    def test_list_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"username": None}, 422),
            ({"email": None}, 422),
            ({"email": "not an email"}, 422),
            ({"user_type": None}, 422),
            ({"user_type": "not correct user_type"}, 422),
            ({"first_name": None}, 201),
            ({"last_name": None}, 201),
            ({"language": "not supported language"}, 422),
            ({"language": None}, 422),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code):
        data = self.payload_create
        data.update(extra_body)

        response = self.do_api_request(
            self.url, "POST", self.user_access_token_frodon.token, data=data
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)

    def test_create_response(self):
        response = self.do_api_request(
            self.url,
            "POST",
            self.user_access_token_frodon.token,
            data=self.payload_create,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)

        obj = User.objects.get(id=data["id"])
        self._assert_api_format(
            data,
            obj,
            [
                "id",
                "username",
                "email",
                "first_name",
                "last_name",
                "language",
                "is_active",
                "user_type",
                "avatar",
                "roles",
            ],
            expand=True,
        )

    @parameterized.expand(
        [
            ("totem.user.create", 201),
            ("totem.user.read", 403),
            ("totem.user.update", 403),
            ("totem.user.delete", 403),
        ]
    )
    def test_create_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url,
            "POST",
            self.user_access_token_frodon.token,
            data=self.payload_create,
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 201:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"email": None}, 422),
            ({"email": "not an email"}, 422),
            ({"user_type": None}, 422),
            ({"user_type": "not correct user_type"}, 422),
            ({"first_name": None}, 200),
            ({"last_name": None}, 200),
            ({"language": "not supported language"}, 422),
            ({"language": None}, 422),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        data = self.payload_update
        data.update(extra_body)

        response = self.do_api_request(
            self.url_detail, "PATCH", self.user_access_token_frodon.token, data=data
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)

    def test_update_response(self):
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)

        obj = User.objects.get(id=USER_ID2)
        self._assert_api_format(
            data,
            obj,
            [
                "id",
                "username",
                "email",
                "first_name",
                "last_name",
                "language",
                "is_active",
                "user_type",
                "avatar",
                "roles",
            ],
            expand=True,
        )

    @parameterized.expand(
        [
            ("totem.user.create", 403),
            ("totem.user.read", 403),
            ("totem.user.update", 200),
            ("totem.user.delete", 403),
        ]
    )
    def test_update_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.user_access_token_frodon.token,
            data=self.payload_update,
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_api_request(
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")

    @parameterized.expand(
        [
            ("totem.user.create", 403),
            ("totem.user.read", 403),
            ("totem.user.update", 403),
            ("totem.user.delete", 204),
        ]
    )
    def test_delete_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_detail, "DELETE", self.user_access_token_frodon.token
        )

        self.assertEqual(response.status_code, status_code)
        if status_code != 204:
            data = response.json()
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Read Profile Operation
    # ------------------------------------------

    def test_profile_read_response(self):
        response = self.do_api_request(
            self.url_profile, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(
            data,
            self.user_access_token_frodon.user,
            [
                "id",
                "username",
                "last_name",
                "first_name",
                "email",
                "language",
                "avatar",
            ],
        )

    @parameterized.expand(
        [
            ("totem.user.create", 200),
            ("totem.user.read", 200),
            ("totem.user.update", 200),
            ("totem.user.delete", 200),
        ]
    )
    def test_profile_read_access_rights(self, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(
            self.url_profile, "GET", self.user_access_token_frodon.token
        )
        data = response.json()

        self.assertEqual(response.status_code, status_code)
        if status_code != 200:
            self.assertEqual(
                data, {"detail": ["You do not have permission to perform this action."]}
            )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(
        self, api_data, obj, fields, expand=True
    ):  # pylint: disable=unused-argument
        if not fields:
            fields = [
                "id",
                "username",
                "email",
                "first_name",
                "last_name",
                "is_active",
                "language",
                "user_type",
                "avatar",
                "roles",
            ]
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "username" in fields:
            self.assertEqual(api_data["username"], obj.username)
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

        # TODO avatar

        if "roles" in fields:
            for role in obj.roles.all():
                role_api_val = {"id": role.pk, "name": role.name}
                self.assertIn(role_api_val, api_data["roles"])
            self.assertEqual(len(api_data["roles"]), len(obj.roles.all()))

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
