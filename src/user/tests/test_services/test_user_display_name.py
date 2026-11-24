from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from user.services import UserService

from user.tests.test_services.common_user import (
    USER_FRODON_ID,
    USER_GOLLUM_ID,
    USER_SAM_ID,
    UserServiceCommonMixin,
)

USER_UNKNOWN_ID = "5263de93-e694-41ef-b873-34610551afcd"


class UserDisplayNameServiceTest(UserServiceCommonMixin, ServiceTestCaseMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.service = self.get_service(UserService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the users.
            ("one pk", [USER_GOLLUM_ID], 2, [USER_GOLLUM_ID]),
            ("in the order of the pks", [USER_SAM_ID, USER_FRODON_ID], 2, [USER_SAM_ID, USER_FRODON_ID]),
            ("a repeated pk appears once", [USER_SAM_ID, USER_SAM_ID], 2, [USER_SAM_ID]),
            ("an unknown pk is absent", [USER_UNKNOWN_ID, USER_SAM_ID], 2, [USER_SAM_ID]),
            # Coerced before the filter, where it would raise: no query at all.
            ("a malformed pk is absent", ["not-a-uuid"], 0, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            users = async_to_sync(self.service.display_name)(pks, ["id", "username"])

        self.assertEqual([str(user.pk) for user in users], expected_pks)
        for user in users:
            self.assertEqual(user.get_deferred_fields() & {"id", "username"}, set())
            self.assertIn("email", user.get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], [USER_FRODON_ID, USER_GOLLUM_ID]),
            ("own profile", ["user_manage_own_profile"], [USER_FRODON_ID]),
            ("all users", ["user_manage_all_user"], [USER_FRODON_ID, USER_GOLLUM_ID]),
            ("both, combined with AND", ["user_manage_own_profile", "user_manage_all_user"], [USER_FRODON_ID]),
            ("anonymous: no role, no rule", None, [USER_FRODON_ID, USER_GOLLUM_ID]),
        ]
    )
    def test_display_name_access_rules(self, label, rules, expected_pks):
        if rules is None:
            service = self.get_service(UserService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(UserService, user=self.user_frodon)

        users = async_to_sync(service.display_name)([USER_FRODON_ID, USER_GOLLUM_ID], ["id", "username"])

        # Out of reach and unknown are told apart by nothing: both are absent.
        self.assertEqual([str(user.pk) for user in users], expected_pks)
