from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from account.models import (
    Account,
    AccountCategory,
    AccountMovement,
    Budget,
    BudgetLine,
    BudgetPosition,
)


class TestBudgetModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.account = Account.objects.create(name="Shop", code="SHOP")
        cls.other_account = Account.objects.create(name="Bank", code="BANK")
        cls.rent = AccountCategory.objects.create(name="Rent", color=3)
        cls.stock = AccountCategory.objects.create(name="Stock", color=5, account=cls.account)
        cls.food = AccountCategory.objects.create(name="Food")

        cls.budget = Budget.objects.create(name="2026", account=cls.account)
        cls.position_rent = BudgetPosition.objects.create(budget=cls.budget, category=cls.rent)
        cls.position_stock = BudgetPosition.objects.create(budget=cls.budget, category=cls.stock)

    def _movement(self, amount, category=None, account=None):
        return AccountMovement.objects.create(
            account=account or self.account, amount=Decimal(amount), name="Line",
            date=timezone.localdate(), category=category,
        )

    def _line(self, position, amount, **kwargs):
        # Through the QuerySet, as the service writes.
        return BudgetLine.objects.bulk_create(
            [BudgetLine(name="Line", position=position, planned_amount=Decimal(amount), **kwargs)]
        )[0]

    # ------------------------------------------
    # Constraints
    # ------------------------------------------

    def test_one_position_per_category(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BudgetPosition.objects.create(budget=self.budget, category=self.rent)

    def test_account_with_budget_is_protected(self):
        Budget.objects.create(name="Bank budget", account=self.other_account)

        with self.assertRaises(ProtectedError):
            self.other_account.delete()

    def test_delete_budget_cascades(self):
        self._line(self.position_rent, "-100")

        self.budget.delete()

        self.assertFalse(BudgetPosition.objects.exists())
        self.assertFalse(BudgetLine.objects.exists())

    def test_delete_category_cascades_to_positions(self):
        self._line(self.position_rent, "-100")

        self.rent.delete()

        self.assertEqual(list(BudgetPosition.objects.all()), [self.position_stock])
        self.assertFalse(BudgetLine.objects.exists())

    # ------------------------------------------
    # Line budget, derived from the position
    # ------------------------------------------

    def test_bulk_create_derives_budget_from_a_resolved_position(self):
        with self.assertNumQueries(1):  # the insert only
            line = self._line(self.position_rent, "-100")

        self.assertEqual(line.budget_id, self.budget.pk)

    def test_bulk_create_derives_budget_from_a_position_id(self):
        line = BudgetLine.objects.bulk_create(
            [BudgetLine(name="Line", position_id=self.position_rent.pk, planned_amount=1)]
        )[0]

        self.assertEqual(BudgetLine.objects.get(pk=line.pk).budget_id, self.budget.pk)

    def test_update_follows_the_position(self):
        other_budget = Budget.objects.create(name="2027", account=self.account)
        other_position = BudgetPosition.objects.create(budget=other_budget, category=self.rent)
        line = self._line(self.position_rent, "-100")

        BudgetLine.objects.filter(pk=line.pk).update(position=other_position)
        self.assertEqual(BudgetLine.objects.get(pk=line.pk).budget_id, other_budget.pk)

        BudgetLine.objects.filter(pk=line.pk).update(position_id=self.position_rent.pk)
        self.assertEqual(BudgetLine.objects.get(pk=line.pk).budget_id, self.budget.pk)

    def test_save_derives_budget(self):
        # The admin path.
        line = BudgetLine(name="Line", position=self.position_stock, planned_amount=1)
        line.save()

        self.assertEqual(line.budget_id, self.budget.pk)

    # ------------------------------------------
    # Computed fields
    # ------------------------------------------

    def test_refresh_computed(self):
        self._line(self.position_rent, "-1000")
        self._line(self.position_rent, "-200.50")
        self._line(self.position_stock, "-300")
        self._movement("-950", self.rent)
        self._movement("-150", self.stock)
        self._movement("-999", self.rent, account=self.other_account)  # another account
        self._movement("5000")  # no category

        # Refreshing the positions refreshes the budget totals reading them.
        BudgetPosition.objects.refresh_computed()

        rent = BudgetPosition.objects.get(pk=self.position_rent.pk)
        self.assertEqual(
            (rent.name, rent.color, rent.total_planned, rent.total_practical),
            ("Rent", 3, Decimal("-1200.50"), Decimal("-950.00")),
        )
        stock = BudgetPosition.objects.get(pk=self.position_stock.pk)
        self.assertEqual((stock.total_planned, stock.total_practical), (Decimal("-300.00"), Decimal("-150.00")))
        budget = Budget.objects.get(pk=self.budget.pk)
        self.assertEqual(
            (budget.total_planned_amount, budget.total_practical_amount),
            (Decimal("-1500.50"), Decimal("-1100.00")),
        )

    def test_refresh_computed_without_lines_nor_movements(self):
        BudgetPosition.objects.refresh_computed()

        rent = BudgetPosition.objects.get(pk=self.position_rent.pk)
        self.assertEqual((rent.total_planned, rent.total_practical), (Decimal("0"), Decimal("0")))
        budget = Budget.objects.get(pk=self.budget.pk)
        self.assertEqual((budget.total_planned_amount, budget.total_practical_amount), (Decimal("0"), Decimal("0")))

    def test_uncategorized_movement_count(self):
        self._movement("-10", self.rent)  # in the budget
        self._movement("-10", self.food)  # a category the budget has no position for
        self._movement("-10", self.food)
        self._movement("50")  # no category
        self._movement("-10", self.food, account=self.other_account)  # another account
        empty = Budget.objects.create(name="Empty", account=self.other_account)

        # One query for the budgets, three for the counts, however many budgets.
        with self.assertNumQueries(4):
            counts = dict(
                (b.pk, b.uncategorized_movement_count)
                for b in Budget.objects.with_computed("uncategorized_movement_count")
            )

        self.assertEqual(counts, {self.budget.pk: 3, empty.pk: 1})
