from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from user.models import User, UserRole
from user.schemas import UserCreateSchema, UserUpdateSchema
from user.services import UserService

USER_ID1 = "14041cce-8719-4637-92b1-51c4ade4b643"
USER_ID2 = "1fea2c88-abd2-4144-a71b-368b45671231"


class TestUserService(TestCase):
    @classmethod
    def setUpTestData(cls):

        cls.role1, cls.role2, cls.role3 = UserRole.objects.bulk_create([
            UserRole(id="CAT1_TEST1", name="Role Cat 1 Test 1"),
            UserRole(id="CAT1_TEST2", name="Role Cat 1 Test 2"),
            UserRole(id="CAT2_TEST1", name="Role Cat 2 Test 1"),
        ])

        cls.user = User.objects.create(
            pk=USER_ID1,
            username="Tintin",
            password="MiL0u4ev3r",
            email="tintin@moulinsart.com",
        )
        cls.user2 = User.objects.create(
            pk=USER_ID2,
            username="Haddock",
            password="MiL0u4ev3r",
            email="haddock@moulinsart.com",
        )
        cls.user2.roles.set([cls.role1, cls.role3])

    def setUp(self):
        super().setUp()
        # A fresh environment per test: it memoizes the acting user's roles, so
        # sharing one across tests would carry a stale access cache over.
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(UserService)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    def test_create_refuses_a_raw_dict(self):
        """Levels 1 and 2 are guaranteed by building the schema, so a dict has no
        guarantee attached and is rejected before any query."""
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"username": "haddock"}])

    def test_update_refuses_a_raw_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": USER_ID1}, {"email": "a@b.com"})

    @parameterized.expand(
        [
            ("email", {"username": "x", "email": "not-an-email", "roles": []}),
            ("user_type", {"username": "x", "email": "x@y.com", "roles": [], "user_type": "not-a-choice"}),
            ("missing email", {"username": "x", "roles": []}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        """Field-level validation happens at construction, not in the service.

        Types, `choices` (converted to an Enum) and required-ness are covered there,
        for every caller and not only the HTTP one. The service never sees the value.
        """
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                UserCreateSchema(**payload)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"username": "haddock", "email": "haddock@lune.com", "roles": []}, 5),
            (
                {"username": "haddock", "email": "haddock@lune.com", "roles": ["CAT1_TEST1"]},
                9,
            ),
            (
                {
                    "username": "haddock",
                    "email": "haddock@lune.com",
                    "roles": ["CAT1_TEST2", "CAT2_TEST1"],
                },
                9,
            ),
            (
                {
                    "username": "haddock",
                    "email": "haddock@moulinsart.com",
                    "roles": ["CAT1_TEST2"],
                },
                9,
            ),
        ]
    )
    def test_create_valid(self, payload, query_count):
        data = UserCreateSchema(**payload)
        with self.assertNumQueries(query_count):
            async_to_sync(self.service.create)([data])

    # Access rules are read before the transactional body starts, so the roles query
    # is paid even when the operation is rejected further down. Only rejection paths
    # are affected; success counts above are unchanged.
    @parameterized.expand(
        [
            (
                {"username": "Tintin", "email": "tintin2@moulinsart.com", "roles": []},
                5,
            ),  # username already exists
            (
                {"username": "haddock", "email": "haddock@lune.com", "roles": ["NOT_EXISTING"]},
                2,
            ),  # role does not exist: rejected before any transaction is opened
            (
                {
                    "username": "haddock",
                    "email": "haddock@lune.com",
                    "roles": ["CAT1_TEST2", "CAT1_TEST1"],
                },
                9,
            ),  # can not have both roles at the same time
        ]
    )
    def test_create_invalid(self, payload, query_count):
        data = UserCreateSchema(**payload)
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError):
                async_to_sync(self.service.create)([data])

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            (
                {"username": "Tintin"},
                ["username"],
                2,
                1,
            ),
            ({"id__in": [USER_ID1, USER_ID2]}, ["id", "username", "is_active"], 2, 2),
            (
                {"id__in": [USER_ID1, USER_ID2]},
                ["id", "username", "is_active", "roles"],
                2,
                2,
            ),
            (
                {"id__in": [USER_ID1, USER_ID2]},
                ["id", "roles"],
                2,
                2,
            ),
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields)
            self.assertEqual(qs.count(), expected_count)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"username": "Tintin"}, {"email": "tintin2@moulinsart.com"}, 5, 1),
            ({"id": USER_ID1}, {"roles": ["CAT1_TEST1"]}, 8, 1),
            (
                {"username": "notfound"},
                {"email": "nouser@moulinsart.com"},
                4,
                0,
            ),  # user nonexistent --> no row updated
            ({"id": USER_ID1}, {"roles": ["CAT1_TEST2", "CAT2_TEST1"]}, 8, 1),
            (
                {"username": "Tintin"},
                {"username": "tintin_updated", "roles": ["CAT1_TEST2"]},
                9,
                1,
            ),
        ]
    )
    def test_update_valid(self, filters, payload, query_count, affected_row):
        data = UserUpdateSchema(**payload)
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)(filters, data)
            self.assertEqual(count, affected_row)

    def test_update_only_writes_the_fields_that_were_set(self):
        """`exclude_unset` is what keeps a partial update partial.

        It matters beyond query counts: `UserQuerySet.update` emits
        `user_change_rights` when `user_type` is in the payload, which invalidates the
        user's tokens.
        """
        data = UserUpdateSchema(email="tintin2@moulinsart.com")

        values = self.service._input_values(
            data, UserUpdateSchema, exclude_unset=True
        )

        self.assertEqual(values, {"email": "tintin2@moulinsart.com"})

    @parameterized.expand(
        [
            (
                {"username": "Tintin"},
                {"roles": ["NOT_EXISTING"]},
                2,
            ),  # role nonexistent: rejected before any transaction is opened
            (
                {"username": "Tintin"},
                {"roles": ["CAT1_TEST2", "CAT1_TEST1"]},
                8,
            ),  # incompatible roles
        ]
    )
    def test_update_invalid(self, filters, payload, query_count):
        data = UserUpdateSchema(**payload)
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError):
                async_to_sync(self.service.update)(filters, data)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"username": "Tintin"}, 16, 1),  # simple row, no relations deleted
            ({"id": USER_ID2, "username": "Tintin"}, 5, 0),  #  no matching row
            (
                {"username": "notfound"},
                5,
                0,
            ),  # user nonexistent --> no row deleted
            (
                {"id": USER_ID2},
                16,
                1,
            ),  # delete with m2m relations, relations should be deleted too
        ]
    )
    def test_delete_valid(self, filters, query_count, affected_row):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)
            self.assertEqual(count, affected_row)
