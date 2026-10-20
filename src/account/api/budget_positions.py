from typing import List

from ninja import FilterSchema, Schema

from core.api import DisplayNameModelControllerMixin, ModelController, ResequenceModelControllerMixin
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    BudgetPositionCreateBodySchema,
    BudgetPositionDisplayNameSchema,
    BudgetPositionFilterSchema,
    BudgetPositionSchema,
    BudgetPositionUpdateSchema,
)
from account.services import BudgetPositionService

from .budgets import BUDGET_PERMISSION_MAP


class BudgetPositionController(
    TokenHasScopePermissionModelControllerMixin,
    DisplayNameModelControllerMixin,
    ResequenceModelControllerMixin,
    ModelController,
):
    """Nested under its budget: every route stays within the budget of the path,
    a creation files the position under it, and `/resequence/` numbers the
    positions of that budget only."""

    api = api_v1
    service = BudgetPositionService

    path_prefix = "/accounting/budget/{budget_id}/positions/"
    auth = [OAuthTokenAuthentication()]
    # The scopes of the budget: a position is part of it.
    permission_map = BUDGET_PERMISSION_MAP

    list_response_schema: Schema = List[BudgetPositionSchema]
    list_filter_schema: FilterSchema = BudgetPositionFilterSchema
    list_ordering_fields = ["sequence", "name", "total_planned", "total_practical"]
    list_ordering_default_fields = ["sequence"]

    retrieve_response_schema: Schema = BudgetPositionSchema
    create_request_schema = BudgetPositionCreateBodySchema
    create_response_schema = BudgetPositionSchema
    update_request_schema = BudgetPositionUpdateSchema
    update_response_schema = BudgetPositionSchema
    display_name_response_schema = BudgetPositionDisplayNameSchema
