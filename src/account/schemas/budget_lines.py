from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from account.models import BudgetLine

from .budget_positions import BudgetPositionDisplayNameSchema
from .budgets import BudgetDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

LINE_FIELDS = ["name", "sequence", "position", "planned_amount"]


class BudgetLineSchema(ModelSchema):
    budget: Optional[BudgetDisplayNameSchema] = None
    position: Optional[BudgetPositionDisplayNameSchema] = None

    class Meta:
        model = BudgetLine
        fields = ["id", "budget", *LINE_FIELDS]
        optional_fields = "__all__"


class BudgetLineCreateSchema(ModelSchema):
    """The input of the service: the budget is part of it, and must be the one of
    the position."""

    class Meta:
        model = BudgetLine
        fields = ["budget", *LINE_FIELDS]
        optional_fields = ["sequence"]


class BudgetLineCreateBodySchema(ModelSchema):
    """The body of the nested API route: the budget comes from its path."""

    class Meta:
        model = BudgetLine
        fields = LINE_FIELDS
        optional_fields = ["sequence"]


class BudgetLineUpdateSchema(ModelSchema):
    class Meta:
        model = BudgetLine
        fields = LINE_FIELDS
        optional_fields = "__all__"


# `budget` is in no input schema but the service's create one: derived from the
# position on every write, it is checked there against the budget a nested route
# names. It is read, like any relation.
# No display name schema: nothing relates to a line.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class BudgetLineFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the name.",
    )
    position: Optional[str] = Field(
        None,
        q="position__id",
        title="Position",
        description="Identifier of the position.",
    )
