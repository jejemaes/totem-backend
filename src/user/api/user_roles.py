from typing import List

from ninja import FilterSchema, Schema

from core.api import BaseModelController, ListModelControllerMixin, Route, route
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.access_policy import access_policy
from user.access_rights import get_all_permission
from user.models import UserRole
from user.schemas import (
    AccessRuleSchema,
    PermissionSchema,
    UserRoleFilterSchema,
    UserRoleSchema,
)
from user.security import (
    TokenHasScopePermission,
    TokenHasScopePermissionModelControllerMixin,
)


class UserRoleController(
    TokenHasScopePermissionModelControllerMixin,
    ListModelControllerMixin,
    BaseModelController,
):
    api = api_v1
    model = UserRole

    path_prefix = "/user-roles/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.userrole.read"],
    }

    list_response_schema: Schema = List[UserRoleSchema]
    list_filter_schema: FilterSchema = UserRoleFilterSchema
    list_ordering_fields = [
        "name",
        "id",
    ]
    list_ordering_default_fields = ["id"]

    @route.get(
        "/permissions/",
        response=List[PermissionSchema],
        permissions=[TokenHasScopePermission("totem.userrole.read")],
        tags=["User Role"],
    )
    def permission_read(self, request):
        permissions = get_all_permission()
        return [{"id": p[0], "name": p[1]} for p in permissions]

    @route.get(
        "/access-rules/",
        response=List[AccessRuleSchema],
        permissions=[TokenHasScopePermission("totem.userrole.read")],
        tags=["User Role"],
    )
    def access_rules_read(self, request):
        result = []
        for rule in access_policy.get_all_rules():
            result.append(
                {
                    "id": rule.identifier,
                    "name": rule.name,
                    "description": rule.description,
                }
            )
        return result
