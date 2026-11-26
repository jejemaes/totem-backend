from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from account.models import Account, AccountCategory
from account.schemas import AccountCreateSchema, AccountUpdateSchema
from account.services import AccountService
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin

from account.tests.test_services.common_account import (
    ACCOUNT_BREE_ID,
    ACCOUNT_MORIA_ID,
    ACCOUNT_SHIRE_ID,
)
from account.tests.test_services.common_account_category import CATEGORY_BREE_ID
from account.tests.test_services.common_account_movement import AccountMovementServiceCommonMixin

ALL_ACCOUNT_IDS = [ACCOUNT_SHIRE_ID, ACCOUNT_BREE_ID, ACCOUNT_MORIA_ID]

CODE_TAKEN = "An account with that code already exists."
NAME_TAKEN = "An account with that name already exists."


class AccountServiceTest(AccountMovementServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `AccountService`: create, read, update, delete.

    No access rules tests: no `BaseRule` is registered for `Account`. No default
    values beyond the model's.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AccountService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, the insert, then the refresh of its
            # stored totals: one grouped read per total, one UPDATE, the read
            # back; and the lookups of the budget positions reaching it.
            ("required fields only", {"code": "RIVENDELL", "name": "Last Homely House"}, 12, {"active": True, "description": None}),
            (
                "every field",
                {"code": "GREY-HAVENS_1", "name": "Mithlond", "description": "West", "active": False},
                12,
                {"active": False, "description": "West"},
            ),
        ]
    )
    def test_create(self, label, payload, query_count, expected_values):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([AccountCreateSchema(**payload)])

        self.assertEqual([account.code for account in instances], [payload["code"]])
        account = Account.objects.get(pk=instances[0].pk)
        self.assertEqual(
            {name: getattr(account, name) for name in ["code", "name", *expected_values]},
            {"code": payload["code"], "name": payload["name"], **expected_values},
        )
        # Refreshed with the creation: zero, never null.
        self.assertAccountTotals(account.pk, "0", "0", "0")

    @parameterized.expand(
        [
            # A named constraint: reported with its message, under no index.
            ("code taken", {"code": "SHIRE", "name": "Hobbiton"}, 5, CODE_TAKEN),
            ("name taken", {"code": "HOBBITON", "name": "Bag End"}, 5, NAME_TAKEN),
        ]
    )
    def test_create_invalid(self, label, payload, query_count, message):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([AccountCreateSchema(**payload)])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(Account.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"code": "RIVENDELL", "name": "Last Homely House"}])

        self.assertEqual(Account.objects.count(), 3)

    # No `test_create_relations`: an account has no relation to write.

    @parameterized.expand(
        [
            ("every input valid", [("RIVENDELL", "Last Homely House"), ("LORIEN", "Caras Galadhon")], 12, None),
            # All or nothing: the valid first input is not written either.
            ("the second input taken", [("RIVENDELL", "Last Homely House"), ("BREE", "Staddle")], 5, "__all__"),
        ]
    )
    def test_create_batch(self, label, accounts, query_count, error_key):
        data = [AccountCreateSchema(code=code, name=name) for code, name in accounts]

        with self.assertNumQueries(query_count):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([account.code for account in instances], ["RIVENDELL", "LORIEN"])
            self.assertEqual(Account.objects.count(), 5)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(Account.objects.filter(code="RIVENDELL").exists())

    @parameterized.expand(
        [
            ("every field", None, {"active": True}),
            ("the fields asked", ["active", "code"], {"active": True}),
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
            ("no filter", {}, ALL_ACCOUNT_IDS),
            ("by code", {"code": "SHIRE"}, [ACCOUNT_SHIRE_ID]),
            ("active ones", {"active": True}, [ACCOUNT_SHIRE_ID, ACCOUNT_BREE_ID]),
            ("by a stored total", {"balance__gt": 0}, [ACCOUNT_SHIRE_ID]),
            ("nothing matches", {"code": "MORDOR"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        # The roles of the acting user, then the accounts.
        with self.assertNumQueries(2):
            pks = [account.pk for account in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by code", ["code"], [ACCOUNT_BREE_ID, ACCOUNT_MORIA_ID, ACCOUNT_SHIRE_ID]),
            ("by a stored total", ["-balance", "code"], [ACCOUNT_SHIRE_ID, ACCOUNT_BREE_ID, ACCOUNT_MORIA_ID]),
            ("by state, then name", ["active", "-name"], [ACCOUNT_MORIA_ID, ACCOUNT_BREE_ID, ACCOUNT_SHIRE_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [account.pk for account in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "code"], {"code"}),
            # Stored totals are columns: reading them costs nothing more.
            ("the stored totals", ["id", "total_debit", "total_credit", "balance"], {"total_debit", "total_credit", "balance"}),
        ]
    )
    def test_read_fields(self, label, fields, loaded):
        with self.assertNumQueries(2):
            accounts = list(async_to_sync(self.service.read)({"id": ACCOUNT_SHIRE_ID}, fields=fields))

        self.assertEqual(len(accounts), 1)
        self.assertFalse(loaded & accounts[0].get_deferred_fields())
        self.assertIn("description", accounts[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the name", {"name": "Bag End, Hobbiton"}, {"name": "Bag End, Hobbiton", "code": "SHIRE"}),
            ("the code", {"code": "SHIRE-1"}, {"code": "SHIRE-1"}),
            ("state and description", {"active": False, "description": "Sold"}, {"active": False, "description": "Sold"}),
            ("the description emptied", {"description": None}, {"description": None}),
        ]
    )
    def test_update(self, label, payload, expected_values):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"id": ACCOUNT_SHIRE_ID}, AccountUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([account.pk for account in queryset], [ACCOUNT_SHIRE_ID])
        account = Account.objects.get(pk=ACCOUNT_SHIRE_ID)
        self.assertEqual({name: getattr(account, name) for name in expected_values}, expected_values)
        # Nothing the totals read was written: they stay.
        self.assertAccountTotals(ACCOUNT_SHIRE_ID, "-100.50", "150.00", "49.50")

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": ACCOUNT_MORIA_ID}, AccountUpdateSchema(description="Delved too deep"))

        account = Account.objects.get(pk=ACCOUNT_MORIA_ID)
        self.assertEqual(
            (account.code, account.name, account.active, account.description),
            ("MORIA", "Khazad-dum", False, "Delved too deep"),
        )

    @parameterized.expand(
        [
            ("code taken", AccountUpdateSchema(code="BREE"), 6, "__all__", CODE_TAKEN),
            ("name taken", AccountUpdateSchema(name="The Prancing Pony"), 6, "__all__", NAME_TAKEN),
            # Built unvalidated, as another caller than the API could: the schema
            # refuses a null name itself. The null check of the service keys it by
            # the index of the payload, before any query.
            ("name set to null", AccountUpdateSchema.model_construct(name=None), 0, 0, None),
        ]
    )
    def test_update_invalid(self, label, data, query_count, error_key, message):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": ACCOUNT_SHIRE_ID}, data)

        self.assertEqual(list(ctx.exception.dict()), [error_key])
        if message:
            self.assertEqual(ctx.exception.dict()[error_key]["__all__"], [message])
        account = Account.objects.get(pk=ACCOUNT_SHIRE_ID)
        self.assertEqual((account.code, account.name), ("SHIRE", "Bag End"))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": ACCOUNT_SHIRE_ID}, {"name": "Hobbiton"})

        self.assertEqual(Account.objects.get(pk=ACCOUNT_SHIRE_ID).name, "Bag End")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"active": True}, AccountUpdateSchema(active=False))

        self.assertEqual(count, 2)
        self.assertCountEqual([account.pk for account in queryset], [ACCOUNT_SHIRE_ID, ACCOUNT_BREE_ID])
        self.assertFalse(Account.objects.filter(active=True).exists())

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"code": "MORDOR"}, AccountUpdateSchema(active=False))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertEqual(Account.objects.filter(active=True).count(), 2)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # The collector reads each table reaching the account -- the invoices
            # included, twice: for the computed fields, then for the delete -- and
            # its own category goes with it (cascade), with what reaches the category:
            # the invoices again, set to no category.
            ("an account with a category", {"id": ACCOUNT_BREE_ID}, 24, 1, [ACCOUNT_SHIRE_ID, ACCOUNT_MORIA_ID]),
            ("an account without category", {"id": ACCOUNT_MORIA_ID}, 17, 1, [ACCOUNT_SHIRE_ID, ACCOUNT_BREE_ID]),
            ("nothing matches", {"code": "MORDOR"}, 5, 0, ALL_ACCOUNT_IDS),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, remaining_pks):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertCountEqual(Account.objects.values_list("pk", flat=True), remaining_pks)
        self.assertEqual(AccountCategory.objects.filter(pk=CATEGORY_BREE_ID).exists(), ACCOUNT_BREE_ID in remaining_pks)

    @parameterized.expand(
        [
            # `AccountMovement.account` is PROTECT: deactivate it instead.
            ("an account with movements", {"id": ACCOUNT_SHIRE_ID}, "AccountMovement.account"),
            # Several accounts, one of them protected: nothing is deleted.
            ("among others", {"id__in": [ACCOUNT_SHIRE_ID, ACCOUNT_MORIA_ID]}, "AccountMovement.account"),
        ]
    )
    def test_delete_protected(self, label, filters, relation):
        # Refused by the collector, before any DELETE; it reads the invoices too.
        with self.assertNumQueries(13):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.delete)(filters)

        self.assertEqual(ctx.exception.code, "protected_error")
        self.assertIn(relation, str(ctx.exception.dict()["__all__"]))
        self.assertEqual(Account.objects.count(), 3)
