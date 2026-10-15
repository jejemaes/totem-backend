from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from account.models import Account

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class AccountDisplayNameSchema(ModelSchema):
    class Meta:
        model = Account
        fields = ["id", "code", "name"]


class AccountSchema(ModelSchema):
    class Meta:
        model = Account
        fields = [
            "id",
            "code",
            "name",
            "description",
            "active",
            "total_debit",
            "total_credit",
            "balance",
            "create_date",
            "update_date",
        ]
        optional_fields = "__all__"


class AccountCreateSchema(ModelSchema):
    class Meta:
        model = Account
        fields = ["code", "name", "description", "active"]
        optional_fields = ["description", "active"]


class AccountUpdateSchema(ModelSchema):
    class Meta:
        model = Account
        fields = ["code", "name", "description", "active"]
        optional_fields = "__all__"


# The totals are in no request schema: derived from the movements, and refused
# there by `core.api.validation` anyway.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class AccountFilterSchema(FilterSchema):
    active: Optional[bool] = Field(
        None,
        title="Active",
        description="Only the active, or only the inactive accounts.",
    )
    search: Optional[str] = Field(
        None,
        q=["code__icontains", "name__icontains"],
        title="Search Term",
        description="Search term in the code or the name.",
    )
