from typing import List, Optional

from ninja import FilterSchema, Schema
from pydantic import UUID4, Field

from core.schemas import ModelSchema
from user.models import User

from .user_roles import UserRoleDisplayNameSchema

# ----------------------------------------------------
# Path Schemas
# ----------------------------------------------------

class ProfilePathParam(Schema):
    id: UUID4

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class UserDisplayNameSchema(ModelSchema):
    class Meta:
        model = User
        fields = ["id", "username"]
        extra_fields_kwargs = {
            "username": {"alias": "login"},
        }


class UserSchema(ModelSchema):

    roles: Optional[List[UserRoleDisplayNameSchema]] = None

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "last_name",
            "first_name",
            "email",
            "is_active",
            "user_type",
            "language",
            "avatar",
            "roles",
        ]
        optional_fields = "__all__"
        extra_fields_kwargs = {
            "username": {"alias": "login"},
        }


class UserCreateSchema(ModelSchema):
    class Meta:
        model = User
        fields = [
            "username",
            "last_name",
            "first_name",
            "email",
            "user_type",
            "language",
            "avatar",
            "roles",
        ]
        extra_fields_kwargs = {
            # request body: `validation_alias` so ONLY "login" is accepted
            "username": {"validation_alias": "login"},
        }


class UserUpdateSchema(ModelSchema):
    class Meta:
        model = User
        fields = [
            "username",
            "last_name",
            "first_name",
            "email",
            "user_type",
            "language",
            "avatar",
            "roles",
        ]
        optional_fields = "__all__"
        extra_fields_kwargs = {
            "username": {"validation_alias": "login"},
        }


class UserProfileSchema(ModelSchema):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "last_name",
            "first_name",
            "email",
            "language",
            "avatar",
        ]
        optional_fields = "__all__"
        extra_fields_kwargs = {
            "username": {"alias": "login"},
        }


class UserProfileUpdateSchema(ModelSchema):
    """Body of the profile update. Distinct from `UserProfileSchema`: a schema
    cannot be both a strict request body and readable from an ORM instance, since
    the former forbids the Django field name on input while the latter requires it.
    """

    class Meta:
        model = User
        fields = [
            "username",
            "last_name",
            "first_name",
            "email",
            "language",
            "avatar",
        ]
        optional_fields = "__all__"
        extra_fields_kwargs = {
            "username": {"validation_alias": "login"},
        }


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class UserFilterSchema(FilterSchema):
    login: Optional[str] = Field(
        None,
        q="username__icontains",
        title="Login",
        description="Search term in the login.",
    )
    email: Optional[str] = Field(
        None,
        q="email__icontains",
        title="Email",
        description="Search term in the email.",
    )
    is_active: Optional[bool] = Field(
        None, title="Is the user activated.", description="Search active or not users."
    )

    search: Optional[str] = Field(
        None,
        q=["username__icontains", "email__icontains"],
        title="Search Term",
        description="Search term in the username or in the email.",
    )
