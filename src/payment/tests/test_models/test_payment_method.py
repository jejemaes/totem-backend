from django.db import IntegrityError, transaction
from django.test import TestCase
from parameterized import parameterized

from payment.models import PaymentMethod

from payment.tests.test_services.common_payment import (
    IBAN_OTHER,
    METHOD_BANK_ID,
    METHOD_CASH_ID,
    PaymentServiceCommonMixin,
)


class PaymentMethodModelTest(PaymentServiceCommonMixin, TestCase):
    """ What `PaymentMethod` holds on every write path: the electronic form of
    the IBAN, and that only a bank method has one. """

    def test_iban_compacted_on_update(self):
        PaymentMethod.objects.filter(pk=METHOD_BANK_ID).update(iban="de89 3704 0044 0532 0130 00")

        self.assertEqual(PaymentMethod.objects.get(pk=METHOD_BANK_ID).iban, IBAN_OTHER)

    def test_iban_compacted_on_save(self):
        # The admin writes through `save()`.
        method = PaymentMethod(code="NEW", name="New", type="bank", iban="DE89 3704 0044 0532 0130 00")
        method.save()

        self.assertEqual(PaymentMethod.objects.get(pk=method.pk).iban, IBAN_OTHER)

    @parameterized.expand(
        [
            ("a bank method without iban", METHOD_BANK_ID, {"iban": None}),
            ("a cash method with an iban", METHOD_CASH_ID, {"iban": IBAN_OTHER}),
            ("a bank method made a cash one", METHOD_BANK_ID, {"type": "cash"}),
        ]
    )
    def test_iban_only_on_bank(self, label, pk, values):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentMethod.objects.filter(pk=pk).update(**values)
