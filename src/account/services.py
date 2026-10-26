from django.db.models import Q, Sum
from django.utils import timezone

from core.services import (
    CreateMixin,
    DeleteMixin,
    Dimension,
    GroupByMixin,
    Measure,
    ReadMixin,
    ResequenceMixin,
    ServiceBase,
    UpdateMixin,
    date_dimensions,
    number_measures,
    share_measure,
)
from account.models import (
    Account,
    AccountCategory,
    AccountMovement,
    Budget,
    BudgetLine,
    BudgetPosition,
)
from account.schemas import (
    AccountCategoryCreateSchema,
    AccountCategoryUpdateSchema,
    AccountCreateSchema,
    AccountMovementCreateSchema,
    AccountMovementUpdateSchema,
    AccountUpdateSchema,
    BudgetCreateSchema,
    BudgetLineCreateSchema,
    BudgetLineUpdateSchema,
    BudgetPositionCreateSchema,
    BudgetPositionUpdateSchema,
    BudgetUpdateSchema,
)


class AccountService(
    CreateMixin[AccountCreateSchema],
    ReadMixin,
    UpdateMixin[AccountUpdateSchema],
    DeleteMixin,
    ServiceBase[Account],
):
    """Deleting an account with movements is refused by its `PROTECT` foreign key,
    reported as a validation error by `DeleteMixin`: deactivate it instead."""


class AccountCategoryService(
    CreateMixin[AccountCategoryCreateSchema],
    ReadMixin,
    UpdateMixin[AccountCategoryUpdateSchema],
    DeleteMixin,
    ServiceBase[AccountCategory],
):
    pass


class AccountMovementService(
    CreateMixin[AccountMovementCreateSchema],
    ReadMixin,
    GroupByMixin,
    UpdateMixin[AccountMovementUpdateSchema],
    DeleteMixin,
    ServiceBase[AccountMovement],
):
    """Every write here goes stale the stored totals of the accounts concerned,
    which the computed-field context of the write refreshes before it commits.

    Grouped by account, category and period. The amount is signed, so its sum is
    the balance: the debits and the credits are measures of their own, as there is
    no direction column to group by.
    """

    group_by_dimensions = {
        "account": Dimension("account"),
        "category": Dimension("category"),
        **date_dimensions("date", ["day", "week", "month", "quarter", "year"]),
    }
    group_by_measures = {
        **number_measures("amount"),
        "debit_sum": Measure(Sum("amount", filter=Q(amount__lt=0)), "amount", label="Debits"),
        "credit_sum": Measure(Sum("amount", filter=Q(amount__gt=0)), "amount", label="Credits"),
        # The share of each category in its period, or in the whole when grouped by
        # category alone.
        **share_measure("amount", exclude=["category"]),
    }

    def validate_data(self, data, instance):
        error = self.ValidationError({})

        # Also a check constraint, which only reports an unkeyed integrity error.
        if "amount" in data and data["amount"] == 0:
            error.add_message("The amount cannot be zero.", key="amount")

        # Policy, not schema: as a field validator it would sit in the migration.
        # Today in the timezone of the site, not in UTC.
        date = data.get("date")
        if date is not None:
            if date > timezone.localdate():
                error.add_message("The date cannot be in the future.", key="date")

        # Relations arrive resolved, as instances: comparing ids costs no query.
        category = data.get("category")
        if category is not None and category.account_id is not None:
            account_id = data["account"].pk if instance is None else instance.account_id
            if category.account_id != account_id:
                error.add_message(
                    "This category belongs to another account.", key="category"
                )

        if error:
            raise error


class BudgetService(
    CreateMixin[BudgetCreateSchema],
    ReadMixin,
    UpdateMixin[BudgetUpdateSchema],
    DeleteMixin,
    ServiceBase[Budget],
):

    async def create(self, data):
        """A budget whose user is not given is the acting user's.

        Here, before the values are extracted: only the input schema still tells a
        user left out from one explicitly set to null, which stays null. Resolved
        afterwards through the user service like any relation, so it is checked
        the same way. Without it, a user whose access rule only reaches their own
        budgets could not create one without naming themselves.
        """
        if self.user is not None:
            data = [
                item if "user" in item.model_fields_set
                else item.model_copy(update={"user": self.user.pk})
                for item in data
            ]
        return await super().create(data)


class BudgetPositionService(
    CreateMixin[BudgetPositionCreateSchema],
    ReadMixin,
    GroupByMixin,
    UpdateMixin[BudgetPositionUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[BudgetPosition],
):
    """Grouped by category, with the planned and practical totals of the positions.

    A budget has one position per category at most, so within one budget a group
    is one position: the aggregates only add up across budgets.
    """

    group_by_dimensions = {"category": Dimension("category")}
    group_by_measures = {
        **number_measures("total_planned", ["sum", "avg"]),
        **number_measures("total_practical", ["sum", "avg"]),
    }

    def validate_data(self, data, instance):
        # The rule of the movements: a position on a category of another account
        # could never read a practical amount, no movement of the budget's account
        # can carry it.
        category = data.get("category")
        if category is None or category.account_id is None:
            return
        account_id = data["budget"].account_id if instance is None else instance.budget.account_id
        if category.account_id != account_id:
            raise self.ValidationError(
                "This category belongs to another account than the budget's.", key="category"
            )


class BudgetLineService(
    CreateMixin[BudgetLineCreateSchema],
    ReadMixin,
    UpdateMixin[BudgetLineUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[BudgetLine],
):
    """`budget` is derived from the position by the QuerySet. It is still part of the
    create schema, so that a caller naming a budget -- the nested API route does --
    gets an error rather than a line silently filed under another one."""

    def validate_data(self, data, instance):
        position = data.get("position")
        if position is None:
            return
        budget_id = data["budget"].pk if instance is None else instance.budget_id
        if position.budget_id != budget_id:
            raise self.ValidationError(
                "This position belongs to another budget.", key="position"
            )
