import uuid
from typing import Optional

from ninja import FilterSchema
from pydantic import Field
from ulid import ULID

from core.schemas import ModelSchema
from user.schemas import UserDisplayNameSchema
from account.models import Budget

from .accounts import AccountDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class BudgetDisplayNameSchema(ModelSchema):
    class Meta:
        model = Budget
        fields = ["id", "name"]


class BudgetSchema(ModelSchema):
    user: Optional[UserDisplayNameSchema] = None
    account: Optional[AccountDisplayNameSchema] = None

    class Meta:
        model = Budget
        fields = [
            "id",
            "name",
            "user",
            "account",
            "active",
            "note",
            "total_planned_amount",
            "total_practical_amount",
            "uncategorized_movement_count",
            "create_date",
            "update_date",
        ]
        optional_fields = "__all__"


class BudgetCreateSchema(ModelSchema):
    class Meta:
        model = Budget
        fields = ["name", "user", "account", "active", "note"]
        optional_fields = ["user", "active", "note"]


class BudgetUpdateSchema(ModelSchema):
    class Meta:
        model = Budget
        fields = ["name", "user", "active", "note"]
        optional_fields = "__all__"


# No `account` in the update schema: the positions were chosen among the
# categories of that account, a move would leave them on another one.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class BudgetFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the name.",
    )
    # Typed after the columns, not `str`: a malformed id is then refused by the
    # schema (422) instead of failing in the database against a UUID column (400).
    user: Optional[uuid.UUID] = Field(
        None,
        q="user__id",
        title="User",
        description="Identifier of the user in charge.",
    )
    account: Optional[ULID] = Field(
        None,
        q="account__id",
        title="Account",
        description="Identifier of the account.",
    )
    active: Optional[bool] = Field(
        None,
        title="Active",
        description="Only the active, or only the inactive budgets.",
    )
