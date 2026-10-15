from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import Account
from account.schemas import AccountCreateSchema, AccountUpdateSchema
from account.services import AccountService
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError

from account.tests.common import ACCOUNT_ID1, ACCOUNT_ID2, ACCOUNT_ID3, AccountTestMixin


class TestAccountService(AccountTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(AccountService)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("lower case code", {"code": "shop2", "name": "Shop 2"}),
            ("space in code", {"code": "SHOP 2", "name": "Shop 2"}),
            ("code too long", {"code": "A" * 51, "name": "Shop 2"}),
            ("missing code", {"name": "Shop 2"}),
            ("missing name", {"code": "SHOP2"}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                AccountCreateSchema(**payload)

    @parameterized.expand([(AccountCreateSchema,), (AccountUpdateSchema,)])
    def test_totals_are_not_writable(self, schema):
        # Derived from the movements: no request schema carries them.
        self.assertFalse({"total_debit", "total_credit", "balance"} & set(schema.model_fields))

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"code": "SHOP2", "name": "Shop 2"}, 10),
            ({"code": "SHOP-2_B", "name": "Shop 2", "description": "Second shop", "active": False}, 10),
        ]
    )
    def test_create_valid(self, payload, query_count):
        data = AccountCreateSchema(**payload)
        # The insert, then the refresh of its stored totals: one grouped read per
        # total, one UPDATE, and the read back of the refreshed values.
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([data])

        # The totals of a new account are refreshed with its creation: zero, not NULL.
        self.assertTotals(instances[0].pk, "0", "0", "0")

    @parameterized.expand(
        [
            ({"code": "SHOP", "name": "Another shop"}, "code"),
            ({"code": "SHOP2", "name": "Shop"}, "name"),
        ]
    )
    def test_create_duplicate(self, payload, dummy):
        data = AccountCreateSchema(**payload)
        with self.assertRaises(ServiceValidationMultiError):
            async_to_sync(self.service.create)([data])

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"code": "SHOP"}, ["id", "code", "balance"], 2, 1),
            ({"active": True}, ["id", "code", "total_debit", "total_credit", "balance"], 2, 2),
            ({"id__in": [ACCOUNT_ID1, ACCOUNT_ID2, ACCOUNT_ID3]}, ["id"], 2, 3),
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        # The roles of the acting user, then the rows: stored totals are columns,
        # reading them costs nothing more.
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields)
            self.assertEqual(qs.count(), expected_count)

    def test_read_totals(self):
        self.assertTotals(ACCOUNT_ID1, "-100.50", "150.00", "49.50")
        self.assertTotals(ACCOUNT_ID2, "0", "0", "0")

    def test_read_order_by_balance(self):
        qs = async_to_sync(self.service.read)(ordering=["-balance"])

        self.assertEqual(list(qs.values_list("id", flat=True))[0], ACCOUNT_ID1)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"id": ACCOUNT_ID1}, {"name": "Main shop"}, 5, 1),
            ({"id": ACCOUNT_ID1}, {"active": False, "description": "Closed"}, 5, 1),
            ({"active": False}, {"active": True}, 5, 1),
            ({"code": "NOTFOUND"}, {"name": "Nothing"}, 4, 0),
        ]
    )
    def test_update_valid(self, filters, payload, query_count, affected_row):
        data = AccountUpdateSchema(**payload)
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)(filters, data)
            self.assertEqual(count, affected_row)

    def test_update_keeps_the_totals(self):
        async_to_sync(self.service.update)({"id": ACCOUNT_ID1}, AccountUpdateSchema(name="Main shop"))

        self.assertTotals(ACCOUNT_ID1, "-100.50", "150.00", "49.50")

    @parameterized.expand(
        [
            ({"id": ACCOUNT_ID1}, {"code": "BANK"}),
            ({"id": ACCOUNT_ID1}, {"name": "Bank"}),
            ({"id": ACCOUNT_ID1}, {"name": None}),
        ]
    )
    def test_update_invalid(self, filters, payload):
        data = AccountUpdateSchema(**payload)
        with self.assertRaises(ServiceValidationMultiError):
            async_to_sync(self.service.update)(filters, data)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"id": ACCOUNT_ID2}, 1),  # its own category goes with it
            ({"id": ACCOUNT_ID3}, 1),
            ({"code": "NOTFOUND"}, 0),
        ]
    )
    def test_delete_valid(self, filters, affected_row):
        count = async_to_sync(self.service.delete)(filters)
        self.assertEqual(count, affected_row)
        self.assertFalse(Account.objects.filter(**filters).exists())

    def test_delete_account_with_movements_is_refused(self):
        with self.assertRaises(ServiceValidationMultiError):
            async_to_sync(self.service.delete)({"id": ACCOUNT_ID1})

        self.assertTrue(Account.objects.filter(pk=ACCOUNT_ID1).exists())
