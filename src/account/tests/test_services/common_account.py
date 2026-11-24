from decimal import Decimal

from account.models import Account
from user.tests.test_services.common_user import UserServiceCommonMixin

ACCOUNT_SHIRE_ID = "01JA0000000000000000000001"
ACCOUNT_BREE_ID = "01JA0000000000000000000002"
ACCOUNT_MORIA_ID = "01JA0000000000000000000003"

ACCOUNT_UNKNOWN_ID = "01JA0000000000000000000099"


class AccountServiceCommonMixin(UserServiceCommonMixin):
    """ Three accounts, on top of the users and roles of `user`: SHIRE (Bag End),
    BREE (The Prancing Pony) and MORIA (Khazad-dum, inactive). No movement here:
    see `common_account_movement`. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.account_shire, cls.account_bree, cls.account_moria = Account.objects.bulk_create([
            Account(id=ACCOUNT_SHIRE_ID, code="SHIRE", name="Bag End"),
            Account(id=ACCOUNT_BREE_ID, code="BREE", name="The Prancing Pony"),
            Account(id=ACCOUNT_MORIA_ID, code="MORIA", name="Khazad-dum", active=False),
        ])
        Account.objects.refresh_computed()

    def assertAccountTotals(self, account_id, debit, credit, balance):
        account = Account.objects.get(pk=account_id)
        self.assertEqual(
            (account.total_debit, account.total_credit, account.balance),
            (Decimal(debit), Decimal(credit), Decimal(balance)),
        )
