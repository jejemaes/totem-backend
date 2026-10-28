from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import ModelController, ResequenceModelControllerMixin
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    BudgetLineCreateBodySchema,
    BudgetLineFilterSchema,
    BudgetLineSchema,
    BudgetLineUpdateSchema,
)
from account.services import BudgetLineService

from .budgets import BUDGET_PERMISSION_MAP


class BudgetLineController(
    TokenHasScopePermissionModelControllerMixin, ResequenceModelControllerMixin, ModelController
):
    """Nested under its budget, like the positions: the stored `BudgetLine.budget`
    is what the path filters on."""

    api = api_v1
    service = BudgetLineService

    path_prefix = "/accounting/budget/{budget_id}/lines/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = BUDGET_PERMISSION_MAP

    list_response_schema: Schema = List[BudgetLineSchema]
    list_filter_schema: FilterSchema = BudgetLineFilterSchema
    list_ordering_fields = ["sequence", "name", "planned_amount"]
    list_ordering_default_fields = ["sequence"]

    retrieve_response_schema: Schema = BudgetLineSchema
    create_request_schema = BudgetLineCreateBodySchema
    create_response_schema = BudgetLineSchema
    update_request_schema = BudgetLineUpdateSchema
    update_response_schema = BudgetLineSchema
