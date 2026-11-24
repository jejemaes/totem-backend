from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.models import AccountCategory, AccountMovement
from account.schemas import AccountCategoryCreateSchema, AccountCategoryUpdateSchema
from account.services import AccountCategoryService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account import ACCOUNT_BREE_ID, ACCOUNT_SHIRE_ID, ACCOUNT_UNKNOWN_ID
from account.tests.test_services.common_account_category import (
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SHIRE_ID,
)
from account.tests.test_services.common_account_movement import (
    MOVEMENT_BREAKFAST_ID,
    MOVEMENT_PIPEWEED_ID,
    AccountMovementServiceCommonMixin,
)

ALL_CATEGORY_IDS = [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID, CATEGORY_BREE_ID]

GENERAL_NAME_TAKEN = "A general category with that name already exists."
ACCOUNT_NAME_TAKEN = "This account already has a category with that name."


class AccountCategoryServiceTest(AccountMovementServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `AccountCategoryService`: create, read, update, delete.

    No access rules tests: no `BaseRule` is registered for `AccountCategory`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountCategoryService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the insert, and the lookups of the budget positions of the
            # new category, once per position field reaching it.
            ("a general category", {"name": "Elevenses"}, 6, {"color": 0, "account_id": None}),
            ("on an account", {"name": "Elevenses", "color": 3, "account": ACCOUNT_SHIRE_ID}, 7, {"color": 3, "account_id": ACCOUNT_SHIRE_ID}),
            # Unique per account: another account's name is free.
            ("another account's name", {"name": "Pipe-weed", "account": ACCOUNT_BREE_ID}, 7, {"account_id": ACCOUNT_BREE_ID}),
            # ...and so is an account's name, as a general category.
            ("an account's name, as general", {"name": "Pipe-weed"}, 6, {"account_id": None}),
        ]
    )
    def test_create(self, label, payload, query_count, expected_values):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([AccountCategoryCreateSchema(**payload)])

        self.assertEqual([category.name for category in instances], [payload["name"]])
        category = AccountCategory.objects.get(pk=instances[0].pk)
        self.assertEqual(
            {name: getattr(category, name) for name in ["name", *expected_values]},
            {"name": payload["name"], **expected_values},
        )

    @parameterized.expand(
        [
            # A unique constraint is reported by the database, under no index.
            ("general name taken", {"name": "Second Breakfast"}, 5, GENERAL_NAME_TAKEN),
            ("account name taken", {"name": "Pipe-weed", "account": ACCOUNT_SHIRE_ID}, 6, ACCOUNT_NAME_TAKEN),
        ]
    )
    def test_create_invalid(self, label, payload, query_count, message):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([AccountCategoryCreateSchema(**payload)])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(AccountCategory.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"name": "Elevenses"}])

        self.assertEqual(AccountCategory.objects.count(), 3)

    @parameterized.expand(
        [
            # The roles, then the account asked.
            ("unknown account", ACCOUNT_UNKNOWN_ID, 2),
        ]
    )
    def test_create_relations(self, label, account_id, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([AccountCategoryCreateSchema(name="Elevenses", account=account_id)])

        self.assertEqual(list(ctx.exception.dict()[0]), ["account"])
        self.assertFalse(AccountCategory.objects.filter(name="Elevenses").exists())

    @parameterized.expand(
        [
            ("every input valid", [("Elevenses", None), ("Supper", ACCOUNT_SHIRE_ID)], 7, None),
            # All or nothing, even across scopes.
            ("the second input taken", [("Elevenses", None), ("Ale", ACCOUNT_BREE_ID)], 6, "__all__"),
        ]
    )
    def test_create_batch(self, label, categories, query_count, error_key):
        data = [AccountCategoryCreateSchema(name=name, account=account) for name, account in categories]

        with self.assertNumQueries(query_count):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([category.name for category in instances], ["Elevenses", "Supper"])
            self.assertEqual(AccountCategory.objects.count(), 5)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(AccountCategory.objects.filter(name="Elevenses").exists())

    @parameterized.expand(
        [
            ("every field", None, {"color": 0}),
            ("the fields asked", ["color", "account"], {"color": 0}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, expected)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", {}, ALL_CATEGORY_IDS),
            ("general ones", {"account__isnull": True}, [CATEGORY_GENERAL_ID]),
            ("of an account", {"account": ACCOUNT_SHIRE_ID}, [CATEGORY_SHIRE_ID]),
            ("by names", {"name__in": ["Second Breakfast", "Pipe-weed"]}, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            ("nothing matches", {"name": "Lembas"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [category.pk for category in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by name", ["name"], [CATEGORY_BREE_ID, CATEGORY_SHIRE_ID, CATEGORY_GENERAL_ID]),
            ("by color, then name", ["-color", "name"], [CATEGORY_SHIRE_ID, CATEGORY_BREE_ID, CATEGORY_GENERAL_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [category.pk for category in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "name"], 2, {"name"}),
            # The account is prefetched, with the fields asked on it.
            ("the account", ["id", "account__code"], 3, set()),
        ]
    )
    def test_read_fields(self, label, fields, query_count, loaded):
        with self.assertNumQueries(query_count):
            categories = list(async_to_sync(self.service.read)({"id": CATEGORY_SHIRE_ID}, fields=fields))
            code = categories[0].account.code if "account__code" in fields else None

        self.assertFalse(loaded & categories[0].get_deferred_fields())
        self.assertIn("color", categories[0].get_deferred_fields())
        if code is not None:
            self.assertEqual(code, "SHIRE")

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the name", CATEGORY_GENERAL_ID, {"name": "Breakfast"}, {"name": "Breakfast", "color": 0}),
            ("the color", CATEGORY_SHIRE_ID, {"color": 5}, {"name": "Pipe-weed", "color": 5}),
            # Unique per scope: the name of another scope is free.
            ("a name of another scope", CATEGORY_BREE_ID, {"name": "Pipe-weed"}, {"name": "Pipe-weed"}),
        ]
    )
    def test_update(self, label, pk, payload, expected_values):
        # The roles, the rows, the UPDATE, and the positions reading the name and
        # the color of the category, which the write may have gone stale.
        with self.assertNumQueries(6):
            count, queryset = async_to_sync(self.service.update)({"id": pk}, AccountCategoryUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([category.pk for category in queryset], [pk])
        category = AccountCategory.objects.get(pk=pk)
        self.assertEqual({name: getattr(category, name) for name in expected_values}, expected_values)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": CATEGORY_SHIRE_ID}, AccountCategoryUpdateSchema(color=7))

        category = AccountCategory.objects.get(pk=CATEGORY_SHIRE_ID)
        self.assertEqual((category.name, category.color, category.account_id), ("Pipe-weed", 7, ACCOUNT_SHIRE_ID))

    @parameterized.expand(
        [
            ("general name taken", None, "Elevenses", "Second Breakfast", GENERAL_NAME_TAKEN),
            ("account name taken", ACCOUNT_SHIRE_ID, "Mushrooms", "Pipe-weed", ACCOUNT_NAME_TAKEN),
        ]
    )
    def test_update_invalid(self, label, account_id, name, taken, message):
        category = AccountCategory.objects.create(name=name, account_id=account_id)

        with self.assertNumQueries(6):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": category.pk}, AccountCategoryUpdateSchema(name=taken))

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(AccountCategory.objects.get(pk=category.pk).name, name)

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": CATEGORY_SHIRE_ID}, {"color": 7})

        self.assertEqual(AccountCategory.objects.get(pk=CATEGORY_SHIRE_ID).color, 3)

    def test_update_batch(self):
        with self.assertNumQueries(6):
            count, queryset = async_to_sync(self.service.update)(
                {"account__isnull": False}, AccountCategoryUpdateSchema(color=9)
            )

        self.assertEqual(count, 2)
        self.assertCountEqual([category.pk for category in queryset], [CATEGORY_SHIRE_ID, CATEGORY_BREE_ID])
        self.assertEqual(
            dict(AccountCategory.objects.values_list("pk", "color")),
            {CATEGORY_GENERAL_ID: 0, CATEGORY_SHIRE_ID: 9, CATEGORY_BREE_ID: 9},
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"name": "Lembas"}, AccountCategoryUpdateSchema(color=9))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(AccountCategory.objects.filter(color=9).exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # `AccountMovement.category` is SET_NULL: the movements stay, uncategorized.
            ("a category in use", {"id": CATEGORY_GENERAL_ID}, 13, 1, [MOVEMENT_BREAKFAST_ID]),
            ("several", {"account__isnull": False}, 13, 2, [MOVEMENT_PIPEWEED_ID]),
            ("nothing matches", {"name": "Lembas"}, 5, 0, []),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, uncategorized_pks):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertFalse(AccountCategory.objects.filter(**filters).exists())
        self.assertEqual(AccountMovement.objects.count(), 3)
        self.assertCountEqual(
            AccountMovement.objects.filter(category__isnull=True).exclude(name="Mathom sale").values_list("pk", flat=True),
            uncategorized_pks,
        )
