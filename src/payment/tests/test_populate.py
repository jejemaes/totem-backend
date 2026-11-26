import io

from django.core.management import call_command
from django.test import TestCase
from parameterized import parameterized

from user.models import UserRole


class PopulateSystemTestCase(TestCase):

    @parameterized.expand([("internal", "USERTYPE_INTERNAL"), ("admin", "USERTYPE_ADMIN")])
    def test_every_user_reads_the_payment_methods(self, label, role):
        # Picked when registering a payment: whoever may pay a document must be
        # able to list them, whatever the roles of `payment` they hold.
        call_command("populate", "user", "--env", "system", stdout=io.StringIO())

        self.assertIn("totem.paymentmethod.read", UserRole.objects.get(pk=role).permissions)
