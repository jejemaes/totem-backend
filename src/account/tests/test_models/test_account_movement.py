from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from account.models import Account, AccountMovement


class TestAccountMovementModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name="Shop", code="SHOP")

    def test_amount_cannot_be_zero(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountMovement.objects.create(
                account=self.account, amount=0, name="Nothing", date=timezone.now()
            )

    def test_queryset_update_stamps_update_date(self):
        movement = AccountMovement.objects.create(
            account=self.account, amount=-5, name="Line", date=timezone.now()
        )
        update_date = movement.update_date

        AccountMovement.objects.filter(pk=movement.pk).update(name="Renamed")

        movement.refresh_from_db()
        self.assertGreater(movement.update_date, update_date)
