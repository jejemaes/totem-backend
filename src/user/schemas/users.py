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


class UserProfileSchema(ModelSchema):
    class Meta:
        model = User
        fields = ["id", "last_name", "first_name", "email", "language", "avatar"]
        optional_fields = "__all__"


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class UserFilterSchema(FilterSchema):
    username: Optional[str] = Field(
        None,
        q="username__icontains",
        title="Username",
        description="Search term in the username.",
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
