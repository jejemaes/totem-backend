from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.services import AccountCategoryService
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account_category import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
    CATEGORY_UNKNOWN_ID,
    AccountCategoryServiceCommonMixin,
)


class AccountCategoryDisplayNameServiceTest(AccountCategoryServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `AccountCategory`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountCategoryService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the categories.
            ("one pk", [CATEGORY_SHIRE_ID], 2, [CATEGORY_SHIRE_ID]),
            ("in the order of the pks", [CATEGORY_BREE_ID, CATEGORY_GENERAL_ID], 2, [CATEGORY_BREE_ID, CATEGORY_GENERAL_ID]),
            ("a repeated pk appears once", [CATEGORY_SHIRE_ID, CATEGORY_SHIRE_ID], 2, [CATEGORY_SHIRE_ID]),
            ("an unknown pk is absent", [CATEGORY_UNKNOWN_ID, CATEGORY_SHIRE_ID], 2, [CATEGORY_SHIRE_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            categories = async_to_sync(self.service.display_name)(pks, ["id", "name", "color"])

        self.assertEqual([category.pk for category in categories], expected_pks)
        for category in categories:
            self.assertFalse({"name", "color"} & category.get_deferred_fields())
            self.assertIn("account_id", category.get_deferred_fields())
