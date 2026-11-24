from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.services import AccountService
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account import (
    ACCOUNT_BREE_ID,
    ACCOUNT_MORIA_ID,
    ACCOUNT_SHIRE_ID,
    ACCOUNT_UNKNOWN_ID,
    AccountServiceCommonMixin,
)


class AccountDisplayNameServiceTest(AccountServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Account`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the accounts.
            ("one pk", [ACCOUNT_BREE_ID], 2, [ACCOUNT_BREE_ID]),
            ("in the order of the pks", [ACCOUNT_MORIA_ID, ACCOUNT_SHIRE_ID], 2, [ACCOUNT_MORIA_ID, ACCOUNT_SHIRE_ID]),
            ("a repeated pk appears once", [ACCOUNT_BREE_ID, ACCOUNT_BREE_ID], 2, [ACCOUNT_BREE_ID]),
            ("an unknown pk is absent", [ACCOUNT_UNKNOWN_ID, ACCOUNT_BREE_ID], 2, [ACCOUNT_BREE_ID]),
            # A ULID field coerces any string: unlike a UUID pk, a malformed one
            # reaches the database, where it matches nothing.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            accounts = async_to_sync(self.service.display_name)(pks, ["id", "code", "name"])

        self.assertEqual([account.pk for account in accounts], expected_pks)
        for account in accounts:
            self.assertFalse({"code", "name"} & account.get_deferred_fields())
            self.assertIn("description", account.get_deferred_fields())
