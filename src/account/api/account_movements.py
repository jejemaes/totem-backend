from typing import List

from ninja import FilterSchema, Schema

from core.api import GroupByModelControllerMixin, ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    AccountMovementCreateSchema,
    AccountMovementFilterSchema,
    AccountMovementSchema,
    AccountMovementUpdateSchema,
)
from account.services import AccountMovementService


class AccountMovementController(
    TokenHasScopePermissionModelControllerMixin, GroupByModelControllerMixin, ModelController
):
    api = api_v1
    service = AccountMovementService

    path_prefix = "/accounting/movements/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.accountmovement.read"],
        "create": ["totem.accountmovement.create"],
        "update": ["totem.accountmovement.update"],
        "delete": ["totem.accountmovement.delete"],
        # A group sums movements the list would show: no scope of its own.
        "group_by": ["totem.accountmovement.read"],
    }

    list_response_schema: Schema = List[AccountMovementSchema]
    list_filter_schema: FilterSchema = AccountMovementFilterSchema
    list_ordering_fields = ["date", "amount", "name", "reference", "create_date"]
    list_ordering_default_fields = ["-date"]

    retrieve_response_schema: Schema = AccountMovementSchema
    create_request_schema = AccountMovementCreateSchema
    create_response_schema = AccountMovementSchema
    update_request_schema = AccountMovementUpdateSchema
    update_response_schema = AccountMovementSchema
