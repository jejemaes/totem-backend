from django.utils import timezone

from core.services import CreateMixin, DeleteMixin, ReadMixin, ServiceBase, UpdateMixin
from account.models import Account, AccountCategory, AccountMovement
from account.schemas import (
    AccountCategoryCreateSchema,
    AccountCategoryUpdateSchema,
    AccountCreateSchema,
    AccountMovementCreateSchema,
    AccountMovementUpdateSchema,
    AccountUpdateSchema,
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
    UpdateMixin[AccountMovementUpdateSchema],
    DeleteMixin,
    ServiceBase[AccountMovement],
):
    """Every write here goes stale the stored totals of the accounts concerned,
    which the computed-field context of the write refreshes before it commits."""

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
