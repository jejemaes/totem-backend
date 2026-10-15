from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone
from parameterized import parameterized

from account.models import Account, AccountMovement


class TestAccountModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name="Shop", code="SHOP")
        cls.other_account = Account.objects.create(name="Bank", code="BANK")

    def _movement(self, account, amount):
        return AccountMovement.objects.create(
            account=account, amount=Decimal(amount), name="Line", date=timezone.localdate()
        )

    @parameterized.expand([("SHOP-2",), ("BANK_01",), ("A",), ("9",)])
    def test_code_format_accepted(self, code):
        Account.objects.create(name=f"Account {code}", code=code)

    @parameterized.expand([("shop",), ("SHOP 2",), ("SHÔP",), ("",), ("A.B",)])
    def test_code_format_refused(self, code):
        # The ORM side of the rule: the regex validator only guards the schemas.
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.create(name=f"Account {code}", code=code)

    @parameterized.expand([({"name": "Shop", "code": "OTHER"},), ({"name": "Other", "code": "SHOP"},)])
    def test_name_and_code_are_unique(self, values):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Account.objects.create(**values)

    def test_account_with_movements_is_protected(self):
        self._movement(self.account, "10.00")

        with self.assertRaises(ProtectedError):
            self.account.delete()

    def test_queryset_update_stamps_update_date(self):
        update_date = self.account.update_date

        Account.objects.filter(pk=self.account.pk).update(description="Main shop")

        self.account.refresh_from_db()
        self.assertGreater(self.account.update_date, update_date)

    # ------------------------------------------
    # Stored computed fields
    # ------------------------------------------

    def test_totals_are_null_until_refreshed(self):
        # Writes around the service layer refresh nothing: that is the contract of
        # stored computed fields, reconciled by `refresh_computed()`.
        self._movement(self.account, "10.00")

        self.account.refresh_from_db()
        self.assertIsNone(self.account.balance)

    def test_refresh_computed(self):
        self._movement(self.account, "100.00")
        self._movement(self.account, "25.50")
        self._movement(self.account, "-40.25")
        self._movement(self.account, "-0.25")
        self._movement(self.other_account, "-999.99")

        Account.objects.filter(pk=self.account.pk).refresh_computed()

        self.account.refresh_from_db()
        self.assertEqual(self.account.total_credit, Decimal("125.50"))
        self.assertEqual(self.account.total_debit, Decimal("-40.50"))
        self.assertEqual(self.account.balance, Decimal("85.00"))

    def test_refresh_computed_without_movements_reads_zero(self):
        Account.objects.filter(pk=self.account.pk).refresh_computed()

        self.account.refresh_from_db()
        self.assertEqual(self.account.total_credit, Decimal("0"))
        self.assertEqual(self.account.total_debit, Decimal("0"))
        self.assertEqual(self.account.balance, Decimal("0"))

    def test_refresh_computed_costs_one_query_per_total(self):
        accounts = [Account(name=f"Account {i}", code=f"ACC{i}") for i in range(5)]
        Account.objects.bulk_create(accounts)
        for account in accounts:
            self._movement(account, "10.00")
            self._movement(account, "-3.00")

        # Whatever the number of accounts: the pks, the rows handed to the prefetch
        # methods, one grouped read per total, and a single UPDATE -- which also
        # recomputes the generated `balance`, at no query of its own.
        with self.assertNumQueries(5):
            Account.objects.filter(pk__in=[a.pk for a in accounts]).refresh_computed()

        for account in Account.objects.filter(pk__in=[a.pk for a in accounts]):
            self.assertEqual(account.balance, Decimal("7.00"))
