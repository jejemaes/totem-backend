from typing import Optional

from django.db.models import Q
from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from account.models import AccountCategory

from .accounts import AccountDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class AccountCategoryDisplayNameSchema(ModelSchema):
    class Meta:
        model = AccountCategory
        fields = ["id", "name", "color"]


class AccountCategorySchema(ModelSchema):
    # Without the annotation the relation serializes to its bare pk, and is not
    # prefetched.
    account: Optional[AccountDisplayNameSchema] = None

    class Meta:
        model = AccountCategory
        fields = ["id", "name", "color", "account"]
        optional_fields = "__all__"


class AccountCategoryCreateSchema(ModelSchema):
    class Meta:
        model = AccountCategory
        fields = ["name", "color", "account"]
        optional_fields = ["color", "account"]


class AccountCategoryUpdateSchema(ModelSchema):
    class Meta:
        model = AccountCategory
        fields = ["name", "color"]
        optional_fields = "__all__"


# No `account` in the update schema: the scope of a category is fixed at creation.
# Scoping a general category to one account would leave it on the movements of
# every other account, against the very rule it stands for.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class AccountCategoryFilterSchema(FilterSchema):
    account: Optional[str] = Field(
        None,
        q="account__id",
        title="Account",
        description="Identifier of the account the categories are scoped to.",
    )
    applicable_to: Optional[str] = Field(
        None,
        title="Applicable To",
        description="Identifier of an account: the categories usable on its movements, "
        "the general ones and its own.",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )

    def filter_applicable_to(self, value):
        if not value:
            return Q()
        return Q(account__isnull=True) | Q(account__id=value)
