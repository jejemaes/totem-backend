from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    BudgetCreateSchema,
    BudgetFilterSchema,
    BudgetSchema,
    BudgetUpdateSchema,
)
from account.services import BudgetService

BUDGET_PERMISSION_MAP = {
    "read": ["totem.budget.read"],
    "create": ["totem.budget.create"],
    "update": ["totem.budget.update"],
    "delete": ["totem.budget.delete"],
}


class BudgetController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = BudgetService

    path_prefix = "/accounting/budget/"
    auth = [OAuthTokenAuthentication()]
    permission_map = BUDGET_PERMISSION_MAP

    list_response_schema: Schema = List[BudgetSchema]
    list_filter_schema: FilterSchema = BudgetFilterSchema
    # The totals are stored columns; `uncategorized_movement_count` is virtual, so
    # it cannot be ordered by.
    list_ordering_fields = ["name", "active", "create_date", "total_planned_amount", "total_practical_amount"]
    list_ordering_default_fields = ["name"]

    retrieve_response_schema: Schema = BudgetSchema
    create_request_schema = BudgetCreateSchema
    create_response_schema = BudgetSchema
    update_request_schema = BudgetUpdateSchema
    update_response_schema = BudgetSchema
