from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from payment.schemas import PaymentMethodCreateSchema, PaymentMethodUpdateSchema

IBAN = "FR7630006000011234567890189"


class PaymentMethodSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("electronic form", IBAN, IBAN),
            ("as printed", "fr76 3000 6000 0112 3456 7890 189", IBAN),
            # Longer than the column with its spaces: compacted before `max_length`.
            ("as printed, the longest", "MT84 MALT 0110 0001 2345 MTLC AST0 01S", "MT84MALT011000012345MTLCAST001S"),
            ("blank", "   ", None),
        ]
    )
    def test_iban_compacted(self, label, value, expected):
        for schema in (PaymentMethodCreateSchema, PaymentMethodUpdateSchema):
            payload = {"code": "NEW", "name": "New", "type": "bank", "iban": value}
            self.assertEqual(schema(**payload).iban, expected)

    @parameterized.expand(
        [
            # `validate_iban`, the validator of the field, runs in the schema.
            ("wrong check digits", "FR7630006000011234567890188", "The check digits of this IBAN are wrong."),
            ("not an iban", "FR76-3000!", "This is not an IBAN."),
            ("an unknown country", "XX7630006000011234567890189", None),
        ]
    )
    def test_iban_invalid(self, label, value, message):
        for schema in (PaymentMethodCreateSchema, PaymentMethodUpdateSchema):
            with self.assertRaises(PydanticValidationError) as ctx:
                schema(code="NEW", name="New", type="bank", iban=value)

            [error] = ctx.exception.errors()
            self.assertEqual(error["loc"], ("iban",))
            if message:
                self.assertIn(message, error["msg"])
