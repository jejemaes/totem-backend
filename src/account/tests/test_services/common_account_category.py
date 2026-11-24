from account.models import AccountCategory

from account.tests.test_services.common_account import AccountServiceCommonMixin

CATEGORY_GENERAL_ID = "01JC0000000000000000000001"
CATEGORY_SHIRE_ID = "01JC0000000000000000000002"
CATEGORY_BREE_ID = "01JC0000000000000000000003"

CATEGORY_UNKNOWN_ID = "01JC0000000000000000000099"


class AccountCategoryServiceCommonMixin(AccountServiceCommonMixin):
    """ On top of the accounts: "Second Breakfast", a general category (no
    account), "Pipe-weed" on SHIRE and "Ale" on BREE. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category_general, cls.category_shire, cls.category_bree = AccountCategory.objects.bulk_create([
            AccountCategory(id=CATEGORY_GENERAL_ID, name="Second Breakfast"),
            AccountCategory(id=CATEGORY_SHIRE_ID, name="Pipe-weed", color=3, account=cls.account_shire),
            AccountCategory(id=CATEGORY_BREE_ID, name="Ale", account=cls.account_bree),
        ])
