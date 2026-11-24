from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from user.services import UserRoleService

from user.tests.test_services.common_user import (
    ROLE_BASE_ID,
    ROLE_HOBBIT_ID,
    ROLE_ORC_ID,
    ROLE_WIZARD_ID,
    UserServiceCommonMixin,
)


class UserRoleServiceTest(UserServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `UserRoleService` is read-only: roles come from the fixtures.

    No access rules tests: no `BaseRule` is registered for `UserRole`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(UserRoleService, user=self.user_frodon)

    # ------------------------------------------
    # Create, Update, Delete
    # ------------------------------------------

    @parameterized.expand([("create",), ("default_values",), ("update",), ("delete",), ("resequence",)])
    def test_operation_is_not_composed(self, operation):
        # The absence of the mixin is the whole contract: nothing else stops a
        # caller writing roles.
        self.assertFalse(hasattr(UserRoleService, operation))

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, [ROLE_HOBBIT_ID, ROLE_WIZARD_ID, ROLE_ORC_ID, ROLE_BASE_ID]),
            ("by pk prefix", {"id__startswith": "FELLOWSHIP_"}, [ROLE_HOBBIT_ID, ROLE_WIZARD_ID]),
            ("by user", {"users__first_name": "Sméagol"}, [ROLE_ORC_ID]),
            ("nothing matches", {"name": "Nazgûl"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        # The roles of the acting user, then the roles.
        with self.assertNumQueries(2):
            pks = [role.pk for role in async_to_sync(self.service.read)(filters, ordering=["id"])]

        self.assertEqual(pks, sorted(expected_pks))
