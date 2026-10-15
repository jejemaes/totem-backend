from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from account.models import AccountCategory, AccountMovement
from account.schemas import AccountCategoryCreateSchema, AccountCategoryUpdateSchema
from account.services import AccountCategoryService
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError

from account.tests.common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    CATEGORY_BANK_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHOP_ID,
    MOVEMENT_ID2,
    AccountTestMixin,
)


class TestAccountCategoryService(AccountTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(AccountCategoryService)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    @parameterized.expand(
        [
            ("missing name", {"color": 1}),
            ("color too high", {"name": "Food", "color": 16}),
            ("color negative", {"name": "Food", "color": -1}),
        ]
    )
    def test_invalid_field_is_rejected_when_building_the_schema(self, dummy, payload):
        with self.assertNumQueries(0):
            with self.assertRaises(PydanticValidationError):
                AccountCategoryCreateSchema(**payload)

    def test_update_schema_has_no_account(self):
        # The scope of a category is fixed at creation.
        self.assertNotIn("account", AccountCategoryUpdateSchema.model_fields)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": "Food"}, 5),
            ({"name": "Food", "color": 3, "account": ACCOUNT_ID1}, 6),
            ({"name": "Stock", "account": ACCOUNT_ID2}, 6),  # another account's name
            ({"name": "Stock"}, 5),  # an account's name, as a general category
        ]
    )
    def test_create_valid(self, payload, query_count):
        data = AccountCategoryCreateSchema(**payload)
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([data])
        self.assertEqual(instances[0].account_id, payload.get("account"))

    @parameterized.expand(
        [
            # A unique constraint is reported by the database, for the whole write:
            # unkeyed, as `__all__`.
            ("general name taken", {"name": "Rent"}, ["__all__", "__all__"]),
            ("account name taken", {"name": "Stock", "account": ACCOUNT_ID1}, ["__all__", "__all__"]),
            # A relation is resolved per payload: keyed by its index.
            ("unknown account", {"name": "Food", "account": "01JA0000000000000000000099"}, [0, "account"]),
        ]
    )
    def test_create_invalid(self, dummy, payload, error_path):
        data = AccountCategoryCreateSchema(**payload)
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([data])
        key, field = error_path
        self.assertIn(field, ctx.exception.dict()[key])

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"account__isnull": True}, ["id", "name"], 2, 1),
            ({"account": ACCOUNT_ID1}, ["id", "name", "account"], 2, 1),
            ({"id__in": [CATEGORY_GENERAL_ID, CATEGORY_SHOP_ID, CATEGORY_BANK_ID]}, ["id", "account"], 2, 3),
        ]
    )
    def test_read_valid(self, filters, fields, query_count, expected_count):
        with self.assertNumQueries(query_count):
            qs = async_to_sync(self.service.read)(filters, fields=fields)
            self.assertEqual(len(qs), expected_count)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"id": CATEGORY_GENERAL_ID}, {"name": "Rental"}, 1),
            ({"id": CATEGORY_SHOP_ID}, {"color": 5}, 1),
            ({"name": "Unknown"}, {"color": 5}, 0),
        ]
    )
    def test_update_valid(self, filters, payload, affected_row):
        data = AccountCategoryUpdateSchema(**payload)
        count, queryset = async_to_sync(self.service.update)(filters, data)
        self.assertEqual(count, affected_row)

    @parameterized.expand(
        [
            ("general name taken", CATEGORY_GENERAL_ID, "Food", "Rent"),
            ("account name taken", CATEGORY_SHOP_ID, "Spare", "Stock"),
        ]
    )
    def test_update_name_taken(self, dummy, scope_of, name, taken):
        account = AccountCategory.objects.get(pk=scope_of).account
        category = AccountCategory.objects.create(name=name, account=account)

        with self.assertRaises(ServiceValidationMultiError):
            async_to_sync(self.service.update)(
                {"id": category.pk}, AccountCategoryUpdateSchema(name=taken)
            )
        category.refresh_from_db()
        self.assertEqual(category.name, name)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete_keeps_the_movements(self):
        count = async_to_sync(self.service.delete)({"id": CATEGORY_GENERAL_ID})

        self.assertEqual(count, 1)
        self.assertIsNone(AccountMovement.objects.get(pk=MOVEMENT_ID2).category_id)
