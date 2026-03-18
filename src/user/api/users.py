from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController, Route, route
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.models import User
from user.schemas import (
    ProfilePathParam,
    UserCreateSchema,
    UserFilterSchema,
    UserProfileSchema,
    UserSchema,
    UserUpdateSchema,
)
from user.security import IsAuthenticated, TokenHasScopePermissionModelControllerMixin


class UserController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    model = User
    service_name = "user.User"

    path_prefix = "/users/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.user.read"],
        "create": ["totem.user.create"],
        "update": ["totem.user.update"],
        "delete": ["totem.user.delete"],
    }

    list_response_schema: Schema = List[UserSchema]
    list_filter_schema: FilterSchema = UserFilterSchema
    list_ordering_fields = [
        "username",
        "email",
        "first_name",
        "is_active",
        "date_joined",
    ]
    list_ordering_default_fields = ["username"]

    retrieve_response_schema: Schema = UserSchema

    create_request_schema = UserCreateSchema
    create_response_schema = UserSchema

    update_request_schema = UserUpdateSchema
    update_response_schema = UserSchema

    # Actions

    @route.get(
        "/me/", response=UserProfileSchema, permissions=[IsAuthenticated], tags=["User"]
    )
    def profile_read(self, request):
        return request.auth.user

    @route.patch(
        "/me/", response=UserProfileSchema, permissions=[IsAuthenticated], tags=["User"]
    )
    def profile_update(self, request, body: UserProfileSchema):
        path_parameters = ProfilePathParam(id=request.auth.user.pk)
        instance = self.update(request, path_parameters, body)
        return instance
