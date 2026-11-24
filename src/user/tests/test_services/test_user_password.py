from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from user.models import User
from user.services import UserService

from user.tests.test_services.common_user import (
    USER_FRODON_ID,
    USER_GOLLUM_ID,
    UserServiceCommonMixin,
)

OLD_PASSWORD = "Pr3cious-Ring"
NEW_PASSWORD = "Mount-D00m-Lava"


class UserPasswordServiceTest(UserServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `change_password` and `set_password`: not `update`, since a password is
    hashed and validated against `AUTH_PASSWORD_VALIDATORS`."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for user in (cls.user_frodon, cls.user_gollum):
            user.set_password(OLD_PASSWORD)
            user.save()

    def setUp(self):
        super().setUp()
        self.service = self.get_service(UserService, user=self.user_frodon)

    # ------------------------------------------
    # Change Password
    # ------------------------------------------

    @parameterized.expand(
        [
            ("valid", OLD_PASSWORD, NEW_PASSWORD, None),
            ("wrong current password", "not-my-password", NEW_PASSWORD, ["old_password"]),
            # `AUTH_PASSWORD_VALIDATORS`, one per validator
            ("too short", OLD_PASSWORD, "Sh0rt", ["new_password"]),
            ("too common", OLD_PASSWORD, "password123", ["new_password"]),
            ("only digits", OLD_PASSWORD, "84629173650", ["new_password"]),
            ("too close to the login", OLD_PASSWORD, "frodon@lacomte.com", ["new_password"]),
            ("both wrong, both reported", "not-my-password", "Sh0rt", ["old_password", "new_password"]),
        ]
    )
    def test_change_password(self, label, old_password, new_password, error_keys):
        # The roles of the acting user are not read: the rules do not apply.
        with self.assertNumQueries(1 if error_keys else 2):
            if error_keys is None:
                result = async_to_sync(self.service.change_password)(old_password, new_password)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.change_password)(old_password, new_password)

        user = User.objects.get(pk=USER_FRODON_ID)
        if error_keys is None:
            self.assertIsNone(result)
            self.assertTrue(user.check_password(NEW_PASSWORD))
        else:
            # Keyed by the pk of the acting user.
            self.assertCountEqual(ctx.exception.dict()[user.pk], error_keys)
            self.assertTrue(user.check_password(OLD_PASSWORD))
        self.assertTrue(User.objects.get(pk=USER_GOLLUM_ID).check_password(OLD_PASSWORD))

    @parameterized.expand(
        [
            ("no rule", []),
            # Not narrowed by the rules: anybody may change their own password.
            ("own profile", ["user_manage_own_profile"]),
            ("all users", ["user_manage_all_user"]),
        ]
    )
    def test_change_password_access_rules(self, label, rules):
        self.role.rules = rules
        self.role.save()
        service = self.get_service(UserService, user=self.user_frodon)

        async_to_sync(service.change_password)(OLD_PASSWORD, NEW_PASSWORD)

        self.assertTrue(User.objects.get(pk=USER_FRODON_ID).check_password(NEW_PASSWORD))

    def test_change_password_anonymous(self):
        # An API key acts as nobody: it has no password of its own to change.
        service = self.get_service(UserService)

        with self.assertNumQueries(0):
            with self.assertRaises(PermissionDenied):
                async_to_sync(service.change_password)(OLD_PASSWORD, NEW_PASSWORD)

    # ------------------------------------------
    # Set Password
    # ------------------------------------------

    @parameterized.expand(
        [
            ("valid", USER_GOLLUM_ID, NEW_PASSWORD, None),
            ("too short", USER_GOLLUM_ID, "Sh0rt", ["new_password"]),
            ("too close to the login of the user set", USER_GOLLUM_ID, "gollum@precious.com", ["new_password"]),
        ]
    )
    def test_set_password(self, label, pk, new_password, error_keys):
        # The roles of the acting user, the user, and the write.
        with self.assertNumQueries(2 if error_keys else 3):
            if error_keys is None:
                async_to_sync(self.service.set_password)(pk, new_password)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.set_password)(pk, new_password)

        user = User.objects.get(pk=pk)
        if error_keys is None:
            self.assertTrue(user.check_password(NEW_PASSWORD))
        else:
            self.assertCountEqual(ctx.exception.dict()[user.pk], error_keys)
            self.assertTrue(user.check_password(OLD_PASSWORD))

    def test_set_password_unknown_user(self):
        with self.assertRaises(User.DoesNotExist):
            async_to_sync(self.service.set_password)("5263de93-e694-41ef-b873-34610551afcd", NEW_PASSWORD)

    @parameterized.expand(
        [
            ("no rule", [], True),
            # Out of reach answers `DoesNotExist`, as for an unknown user.
            ("own profile", ["user_manage_own_profile"], False),
            ("all users", ["user_manage_all_user"], True),
            ("both, combined with AND", ["user_manage_own_profile", "user_manage_all_user"], False),
            ("anonymous: no role, no rule", None, True),
        ]
    )
    def test_set_password_access_rules(self, label, rules, reached):
        if rules is None:
            service = self.get_service(UserService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(UserService, user=self.user_frodon)

        if reached:
            async_to_sync(service.set_password)(USER_GOLLUM_ID, NEW_PASSWORD)
        else:
            with self.assertRaises(User.DoesNotExist):
                async_to_sync(service.set_password)(USER_GOLLUM_ID, NEW_PASSWORD)

        self.assertEqual(User.objects.get(pk=USER_GOLLUM_ID).check_password(NEW_PASSWORD), reached)
