from typing import List

from ninja import FilterSchema, Schema

from core.api import DisplayNameModelControllerMixin, ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    AccountCreateSchema,
    AccountDisplayNameSchema,
    AccountFilterSchema,
    AccountSchema,
    AccountUpdateSchema,
)
from account.services import AccountService


class AccountController(
    TokenHasScopePermissionModelControllerMixin, DisplayNameModelControllerMixin, ModelController
):
    api = api_v1
    service = AccountService

    path_prefix = "/accounting/accounts/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.account.read"],
        "create": ["totem.account.create"],
        "update": ["totem.account.update"],
        "delete": ["totem.account.delete"],
        "display_name": ["totem.account.read"],
    }

    list_response_schema: Schema = List[AccountSchema]
    list_filter_schema: FilterSchema = AccountFilterSchema
    # The totals are stored columns, so they can be ordered by.
    list_ordering_fields = [
        "code",
        "name",
        "active",
        "total_debit",
        "total_credit",
        "balance",
        "create_date",
    ]
    list_ordering_default_fields = ["code"]

    retrieve_response_schema: Schema = AccountSchema
    create_request_schema = AccountCreateSchema
    create_response_schema = AccountSchema
    update_request_schema = AccountUpdateSchema
    update_response_schema = AccountSchema
    display_name_response_schema = AccountDisplayNameSchema
