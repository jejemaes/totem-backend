from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from parameterized import parameterized

from account.models import Account, AccountCategory, AccountMovement


class TestAccountCategoryModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name="Shop", code="SHOP")
        cls.other_account = Account.objects.create(name="Bank", code="BANK")
        cls.general = AccountCategory.objects.create(name="Rent")
        cls.scoped = AccountCategory.objects.create(name="Stock", account=cls.account)

    def test_general_name_is_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountCategory.objects.create(name="Rent")

    def test_name_is_unique_per_account(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountCategory.objects.create(name="Stock", account=self.account)

    @parameterized.expand(
        [
            ("same name on another account", "Stock", "other_account"),
            ("general name reused on an account", "Rent", "account"),
            ("account name reused as general", "Stock", None),
        ]
    )
    def test_name_may_repeat_across_scopes(self, dummy, name, account):
        AccountCategory.objects.create(name=name, account=getattr(self, account) if account else None)

    @parameterized.expand([(-1,), (16,)])
    def test_color_out_of_range(self, color):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountCategory.objects.create(name="Colored", color=color)

    def test_deleting_a_category_keeps_its_movements(self):
        movement = AccountMovement.objects.create(
            account=self.account, amount=-5, name="Line", date=timezone.localdate(), category=self.general
        )

        self.general.delete()

        movement.refresh_from_db()
        self.assertIsNone(movement.category)
