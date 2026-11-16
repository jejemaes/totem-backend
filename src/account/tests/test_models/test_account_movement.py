from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from account.models import Account, AccountMovement
from contact.models import Contact


class TestAccountMovementModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name="Shop", code="SHOP")

    def test_amount_cannot_be_zero(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountMovement.objects.create(
                account=self.account, amount=0, name="Nothing", date=timezone.localdate()
            )

    def test_queryset_update_stamps_update_date(self):
        movement = AccountMovement.objects.create(
            account=self.account, amount=-5, name="Line", date=timezone.localdate()
        )
        update_date = movement.update_date

        AccountMovement.objects.filter(pk=movement.pk).update(name="Renamed")

        movement.refresh_from_db()
        self.assertGreater(movement.update_date, update_date)

    def test_deleting_the_contact_keeps_the_movement(self):
        contact = Contact.objects.create(first_name="Lobelia", last_name="Sackville-Baggins")
        movement = AccountMovement.objects.create(
            account=self.account, amount=150, name="Sale", date=timezone.localdate(), contact=contact
        )

        contact.delete()

        movement.refresh_from_db()
        self.assertIsNone(movement.contact_id)
