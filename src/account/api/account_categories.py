from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, ModelController
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    AccountCategoryCreateSchema,
    AccountCategoryDisplayNameSchema,
    AccountCategoryFilterSchema,
    AccountCategorySchema,
    AccountCategoryUpdateSchema,
)
from account.services import AccountCategoryService


class AccountCategoryController(
    TokenHasScopePermissionModelControllerMixin, DisplayNameModelControllerMixin, ModelController
):
    api = api_v1
    service = AccountCategoryService

    path_prefix = "/accounting/categories/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.accountcategory.read"],
        "create": ["totem.accountcategory.create"],
        "update": ["totem.accountcategory.update"],
        "delete": ["totem.accountcategory.delete"],
        "display_name": ["totem.accountcategory.read"],
    }

    list_response_schema: Schema = List[AccountCategorySchema]
    list_filter_schema: FilterSchema = AccountCategoryFilterSchema
    list_ordering_fields = ["name", "color"]
    list_ordering_default_fields = ["name"]

    retrieve_response_schema: Schema = AccountCategorySchema
    create_request_schema = AccountCategoryCreateSchema
    create_response_schema = AccountCategorySchema
    update_request_schema = AccountCategoryUpdateSchema
    update_response_schema = AccountCategorySchema
    display_name_response_schema = AccountCategoryDisplayNameSchema
