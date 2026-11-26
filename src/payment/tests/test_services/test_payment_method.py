from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from payment.models import PaymentMethod
from payment.schemas import PaymentMethodCreateSchema, PaymentMethodUpdateSchema
from payment.services import PaymentMethodService

from payment.tests.test_services.common_payment import (
    IBAN_BANK,
    IBAN_OTHER,
    METHOD_BANK_ID,
    METHOD_CASH_ID,
    PaymentServiceCommonMixin,
)


class PaymentMethodServiceTest(PaymentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `PaymentMethodService`: the IBAN of a bank method, its form and its
    rules. The IBAN itself is judged by `validate_iban`, the validator of the
    field, which the request schemas run already: see `test_schemas`.

    No access rules tests: no `BaseRule` is registered for `PaymentMethod`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(PaymentMethodService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a bank method", {"type": "bank", "iban": IBAN_OTHER}, IBAN_OTHER),
            # Stored in its electronic form, whatever was typed.
            ("an iban as printed", {"type": "bank", "iban": "de89 3704 0044 0532 0130 00"}, IBAN_OTHER),
            ("a cash method", {"type": "cash"}, None),
            ("a cash method, a blank iban", {"type": "cash", "iban": "  "}, None),
        ]
    )
    def test_create(self, label, payload, iban):
        [method] = async_to_sync(self.service.create)(
            [PaymentMethodCreateSchema(code="NEW", name="New", **payload)]
        )

        self.assertEqual(PaymentMethod.objects.get(pk=method.pk).iban, iban)

    @parameterized.expand(
        [
            ("a bank method without iban", {"type": "bank"}),
            ("a bank method, a blank iban", {"type": "bank", "iban": ""}),
            ("a cash method with an iban", {"type": "cash", "iban": IBAN_OTHER}),
            # An invalid IBAN is refused by the schema already: `test_schemas`.
        ]
    )
    def test_create_invalid(self, label, payload):
        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.create)([PaymentMethodCreateSchema(code="NEW", name="New", **payload)])

        self.assertEqual(list(context.exception.dict()[0]), ["iban"])
        self.assertFalse(PaymentMethod.objects.filter(code="NEW").exists())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("another iban", METHOD_BANK_ID, {"iban": "DE89 3704 0044 0532 0130 00"}, "bank", IBAN_OTHER),
            ("a cash method made a bank one", METHOD_CASH_ID, {"type": "bank", "iban": IBAN_OTHER}, "bank", IBAN_OTHER),
            ("a bank method made a cash one", METHOD_BANK_ID, {"type": "cash", "iban": None}, "cash", None),
            ("the name only", METHOD_BANK_ID, {"name": "Bank of Bree"}, "bank", IBAN_BANK),
        ]
    )
    def test_update(self, label, pk, payload, method_type, iban):
        count, _queryset = async_to_sync(self.service.update)({"id": pk}, PaymentMethodUpdateSchema(**payload))

        self.assertEqual(count, 1)
        method = PaymentMethod.objects.get(pk=pk)
        self.assertEqual((method.type, method.iban), (method_type, iban))

    @parameterized.expand(
        [
            ("a bank method loses its iban", METHOD_BANK_ID, {"iban": None}),
            # The IBAN stays, the type changes under it.
            ("a bank method made a cash one", METHOD_BANK_ID, {"type": "cash"}),
            ("a cash method made a bank one", METHOD_CASH_ID, {"type": "bank"}),
            ("a cash method given an iban", METHOD_CASH_ID, {"iban": IBAN_OTHER}),
        ]
    )
    def test_update_invalid(self, label, pk, payload):
        before = PaymentMethod.objects.values("type", "iban").get(pk=pk)

        with self.assertRaises(ServiceValidationMultiError) as context:
            async_to_sync(self.service.update)({"id": pk}, PaymentMethodUpdateSchema(**payload))

        self.assertEqual(list(context.exception.dict()[pk]), ["iban"])
        self.assertEqual(PaymentMethod.objects.values("type", "iban").get(pk=pk), before)
