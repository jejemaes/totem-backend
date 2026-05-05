from unittest.mock import patch

from django.test import TestCase
from parameterized import parameterized

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from user import choices
from user.models import User, UserRole

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

        cls.env = Environment(user=cls.user, language="en-us")
        cls.service_name = "user.User"

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ([{"username": "haddock"}], 5),
            ([{"username": "haddock", "roles": ["CAT1_TEST1"]}], 9),
            ([{"username": "haddock", "roles": ["CAT1_TEST2", "CAT2_TEST1"]}], 9),
            (
                [
                    {
                        "username": "haddock",
                        "email": "haddock@moulinsart.com",
                        "roles": ["CAT1_TEST2"],
                    }
                ],
                9,
            ),
        ]
    )
    def test_create_valid(self, payload, query_count):
        with self.assertNumQueries(query_count):
            self.env[self.service_name].create(payload)

    @parameterized.expand(
        [
            ([{"username": "Tintin"}], 4),  # username already exists
            (
                [{"username": "newuser", "email": "not-an-email"}],
                3,
            ),  # invalid email
            (
                [{"username": "haddock", "roles": ["NOT_EXISTING"]}],
                4,
            ),  # role does not exist
            (
                [{"username": "haddock", "roles": ["CAT1_TEST2", "CAT1_TEST1"]}],
                9,
            ),  # can not have both roles at the same time
        ]
    )
    def test_create_invalid(self, payload, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError):
                self.env[self.service_name].create(payload)

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
            qs = self.env[self.service_name].read(filters, fields=fields)
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
    def test_update_valid(self, filters, data, query_count, affected_row):
        with self.assertNumQueries(query_count):
            count, queryset = self.env[self.service_name].update(filters, data)
            self.assertEqual(count, affected_row)

    @parameterized.expand(
        [
            (
                {"username": "Tintin"},
                {"email": "not-an-email"},
                4,
            ),  # email invalid
            (
                {"username": "Tintin"},
                {"roles": ["NOT_EXISTING"]},
                5,
            ),  # role nonexistent
            (
                {"username": "Tintin"},
                {"roles": ["CAT1_TEST2", "CAT1_TEST1"]},
                8,
            ),  # incompatible roles
        ]
    )
    def test_update_invalid(self, filters, data, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError):
                self.env[self.service_name].update(filters, data)

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
            count = self.env[self.service_name].delete(filters)
            self.assertEqual(count, affected_row)
