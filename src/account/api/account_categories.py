from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    AccountCategoryCreateSchema,
    AccountCategoryFilterSchema,
    AccountCategorySchema,
    AccountCategoryUpdateSchema,
)
from account.services import AccountCategoryService


class AccountCategoryController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = AccountCategoryService

    path_prefix = "/accounting/categories/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.accountcategory.read"],
        "create": ["totem.accountcategory.create"],
        "update": ["totem.accountcategory.update"],
        "delete": ["totem.accountcategory.delete"],
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
