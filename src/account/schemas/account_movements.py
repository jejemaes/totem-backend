from datetime import datetime
from typing import Literal, Optional

from django.db.models import Q
from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from account.models import AccountMovement

from .account_categories import AccountCategoryDisplayNameSchema
from .accounts import AccountDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

MOVEMENT_FIELDS = ["amount", "name", "description", "date", "reference", "category"]


class AccountMovementSchema(ModelSchema):
    account: Optional[AccountDisplayNameSchema] = None
    category: Optional[AccountCategoryDisplayNameSchema] = None

    class Meta:
        model = AccountMovement
        fields = ["id", "account", *MOVEMENT_FIELDS, "create_date", "update_date"]
        optional_fields = "__all__"


class AccountMovementCreateSchema(ModelSchema):
    class Meta:
        model = AccountMovement
        fields = ["account", *MOVEMENT_FIELDS]
        optional_fields = ["description", "reference", "category"]


class AccountMovementUpdateSchema(ModelSchema):
    class Meta:
        model = AccountMovement
        fields = MOVEMENT_FIELDS
        optional_fields = "__all__"


# No `account` in the update schema: moving a movement to another account would
# move money between their balances behind a correction of a line, and would have
# to re-check the scope of its category. Delete it and create it on the right one.
# No display name schema: nothing relates to a movement.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class AccountMovementFilterSchema(FilterSchema):
    account: Optional[str] = Field(
        None,
        q="account__id",
        title="Account",
        description="Identifier of the account.",
    )
    category: Optional[str] = Field(
        None,
        q="category__id",
        title="Category",
        description="Identifier of the category.",
    )
    date_from: Optional[datetime] = Field(
        None,
        q="date__gte",
        title="From",
        description="Movements on or after this date.",
    )
    date_to: Optional[datetime] = Field(
        None,
        q="date__lte",
        title="To",
        description="Movements on or before this date.",
    )
    direction: Optional[Literal["debit", "credit"]] = Field(
        None,
        title="Direction",
        description="`debit` for the expenses (negative amounts), `credit` for the "
        "revenues (positive amounts).",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains", "reference__icontains"],
        title="Search Term",
        description="Search term in the name or the reference.",
    )

    def filter_direction(self, value):
        # The sign of the amount is the direction: there is no column for it.
        if value == "debit":
            return Q(amount__lt=0)
        if value == "credit":
            return Q(amount__gt=0)
        return Q()
