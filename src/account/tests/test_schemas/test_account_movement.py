from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.schemas import AccountMovementCreateSchema, AccountMovementUpdateSchema

ACCOUNT_ID = "01JA0000000000000000000001"
PAYLOAD = {"account": ACCOUNT_ID, "amount": "-12.30", "name": "Bar tab", "date": "2026-10-01"}


class AccountMovementSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("account missing", "account", None, "account"),
            ("amount missing", "amount", None, "amount"),
            ("name missing", "name", None, "name"),
            ("date missing", "date", None, "date"),
            ("too many decimals", "amount", "1.001", "amount"),
            ("not a date", "date", "yesterday", "date"),
            # A date, not a datetime: a time of day is no part of a movement.
            ("a time", "date", "2026-10-01T09:30:00Z", "date"),
        ]
    )
    def test_create_schema_invalid(self, label, name, value, field):
        payload = {key: val for key, val in PAYLOAD.items() if key != name}
        if value is not None:
            payload[name] = value

        with self.assertRaises(PydanticValidationError) as ctx:
            AccountMovementCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand(
        [
            ("too many decimals", {"amount": "1.001"}, "amount"),
            ("a time", {"date": "2026-10-01T09:30:00Z"}, "date"),
        ]
    )
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            AccountMovementUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_has_no_account(self):
        # A movement does not change account: see the schema module.
        self.assertNotIn("account", AccountMovementUpdateSchema.model_fields)
