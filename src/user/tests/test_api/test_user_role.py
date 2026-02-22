from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.choices import UserType
from user.models import User, UserRole

from .common import USER_ID3, CommonTestMixin

USER_ID4 = "49c7b4f5-b436-4c47-bea1-d3e60b9ab492"
USER_ID5 = "5263de93-e694-11ef-b873-34610551afcd"

ROLE_ID1 = "USERTYPE_NOOB"
ROLE_ID2 = "USERTYPE_ADVANCED"
ROLE_ID3 = "SCOUT_LEADER"
ROLE_ID4 = "SCOUT_KID"
ROLE_ADMIN = "ADMIN"


@freeze_time("2024-11-18 11:12:13")
class UserAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_pipin = User.objects.create(
            id=USER_ID3,
            username="pipin@lacomte.com",
            email="pipin@lacomte.com",
            user_type=UserType.INTERNAL,
        )
        cls.user_galadriel = User.objects.create(
            id=USER_ID4,
            username="galadriel@elfe.com",
            email="galadriel@elfe.com",
            user_type=UserType.INTERNAL,
            is_active=False,
        )

        cls.roles = UserRole.objects.bulk_create(
            [
                UserRole(
                    id=ROLE_ID1,
                    name="Noobie",
                    permissions=[],
                    rules=[],
                ),
                UserRole(
                    id=ROLE_ID2,
                    name="Advanced User",
                    permissions=[],
                    rules=[],
                ),
                UserRole(
                    id=ROLE_ID3,
                    name="Scout Leader",
                    permissions=[],
                    rules=[],
                ),
                UserRole(
                    id=ROLE_ID4,
                    name="Scout Kid",
                    permissions=[],
                    rules=[],
                ),
            ]
        )
        cls.user_frodon.roles.add(cls.roles[0])
        cls.user_access_token_frodon.scope = "totem.userrole.read"
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/user-roles/"

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
        self.assertEqual(len(data["results"]), 5)
        self.assertEqual(data["count"], 5)

        for item in data["results"]:
            obj = UserRole.objects.get(id=item["id"])
            self._assert_api_format(
                item,
                obj,
                [
                    "id",
                    "name",
                    "permissions",
                    "rules",
                ],
            )

    @parameterized.expand(
        [
            ({"name": "elfe"}, []),
            ({"name": "Scout Kid"}, [ROLE_ID4]),
        ]
    )
    def test_list_filters(self, filters, ids):
        qs = UserRole.objects.filter(pk__in=ids)

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
                    "name",
                    "permissions",
                    "rules",
                ],
            )

    @parameterized.expand(
        [
            ([], ["id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
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

        queryset = UserRole.objects.all().order_by(*order_by)

        for instance, item in zip(queryset, data["results"]):
            self.assertEqual(str(instance.pk), item["id"])

    @parameterized.expand(
        [
            (
                [],
                [
                    "id",
                    "name",
                    "permissions",
                    "rules",
                ],
                4,
            ),  # default means all fields
            (["name"], ["id", "name"], 4),
            (
                ["rules", "name"],
                ["id", "rules", "name"],
                4,
            ),
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
            for obj in UserRole.objects.filter(
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
            (["not_existing_field", "name"],),
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
            ("scout", [ROLE_ID3, ROLE_ID4]),
            ("oobi", [ROLE_ID1]),
            ("no-match", []),
        ]
    )
    def test_list_searching(self, search_term, ids):
        qs = UserRole.objects.filter(pk__in=ids)

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
                    "name",
                    "permissions",
                    "rules",
                ],
            )

    @parameterized.expand(
        [
            ("totem.userrole.create", 403),
            ("totem.userrole.read", 200),
            ("totem.userrole.update", 403),
            ("totem.userrole.delete", 403),
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
                data, {"message": "You do not have permission to perform this action."}
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
                "name",
                "permissions",
                "rules",
            ]

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "permissions" in fields:
            self.assertEqual(
                set(api_data["permissions"]), set(obj.permissions)
            )
        if "rules" in fields:
            self.assertEqual(set(api_data["rules"]), set(obj.rules))

        self.assertEqual(
            set(fields),
            set(api_data.keys()),
        )
