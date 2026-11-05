from typing import List
from uuid import UUID

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, ModelController, Route, route
from core.services import ServiceValidationMultiError
from totem.api import api_v1
from user.schemas import (
    ProfilePathParam,
    UserCreateSchema,
    UserDisplayNameSchema,
    UserFilterSchema,
    UserPasswordChangeSchema,
    UserPasswordSetSchema,
    UserProfileSchema,
    UserProfileUpdateSchema,
    UserSchema,
    UserUpdateSchema,
)
from user.security import (
    IsAuthenticated,
    TokenHasScopePermission,
    TokenHasScopePermissionModelControllerMixin,
)
from user.services import UserService


class UserController(
    TokenHasScopePermissionModelControllerMixin, DisplayNameModelControllerMixin, ModelController
):
    api = api_v1
    service = UserService

    path_prefix = "/users/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.user.read"],
        "create": ["totem.user.create"],
        "update": ["totem.user.update"],
        "delete": ["totem.user.delete"],
        "display_name": ["totem.user.read"],
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
    display_name_response_schema = UserDisplayNameSchema

    # Actions

    @route.get(
        "/me/", response=UserProfileSchema, permissions=[IsAuthenticated], tags=["User"]
    )
    async def profile_read(self, request):
        return request.auth.user

    @route.patch(
        "/me/", response=UserProfileSchema, permissions=[IsAuthenticated], tags=["User"]
    )
    async def profile_update(self, request, body: UserProfileUpdateSchema):
        path_parameters = ProfilePathParam(id=request.auth.user.pk)
        instance = await self.update(request, path_parameters, body)
        return instance

    # `/me/password/` is written before `/{id}/password/`, so that it is matched
    # first: the other way round, `me` would be taken for an id.

    @route.post(
        "/me/password/",
        response={204: None},
        permissions=[IsAuthenticated],
        operation_id="userProfilePasswordChange",
        summary="Change My Password",
        tags=["User"],
    )
    async def profile_password_change(self, request, body: UserPasswordChangeSchema):
        try:
            await request.env.get(self.service).change_password(body.old_password, body.new_password)
        except ServiceValidationMultiError as exc:
            # No response schema to translate against: the service reports the
            # keys of the body itself. `loc` as pydantic would write it for this
            # argument, so that a client reads both kinds of error the same way.
            raise self.service_validation_error_to_api_error(exc, None, loc_path=["body", "body"])
        return 204, None

    @route.post(
        "/{id}/password/",
        response={204: None},
        permissions=[TokenHasScopePermission(["totem.user.password"])],
        operation_id="userPasswordSet",
        summary="Set the Password of a User",
        tags=["User"],
    )
    async def password_set(self, request, id: UUID, body: UserPasswordSetSchema):
        try:
            await request.env.get(self.service).set_password(id, body.new_password)
        except ServiceValidationMultiError as exc:
            raise self.service_validation_error_to_api_error(exc, None, loc_path=["body", "body"])
        return 204, None
