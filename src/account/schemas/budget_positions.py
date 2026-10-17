from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from account.models import BudgetPosition

from .account_categories import AccountCategoryDisplayNameSchema
from .budgets import BudgetDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class BudgetPositionDisplayNameSchema(ModelSchema):
    class Meta:
        model = BudgetPosition
        fields = ["id", "name", "color"]


class BudgetPositionSchema(ModelSchema):
    budget: Optional[BudgetDisplayNameSchema] = None
    category: Optional[AccountCategoryDisplayNameSchema] = None

    class Meta:
        model = BudgetPosition
        fields = ["id", "sequence", "name", "color", "budget", "category", "total_planned", "total_practical"]
        optional_fields = "__all__"


class BudgetPositionCreateSchema(ModelSchema):
    """The input of the service: the budget is part of it."""

    class Meta:
        model = BudgetPosition
        fields = ["budget", "sequence", "category"]
        optional_fields = ["sequence"]


class BudgetPositionCreateBodySchema(ModelSchema):
    """The body of the nested API route: the budget comes from its path."""

    class Meta:
        model = BudgetPosition
        fields = ["sequence", "category"]
        optional_fields = ["sequence"]


class BudgetPositionUpdateSchema(ModelSchema):
    class Meta:
        model = BudgetPosition
        fields = ["sequence", "category"]
        optional_fields = "__all__"


# No `budget` in the update schema: a position does not move to another budget.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class BudgetPositionFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the name (the name of the category).",
    )
