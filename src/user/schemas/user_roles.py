from typing import Optional

from ninja import Schema
from pydantic import Field

from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from user.models import UserRole

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class UserRoleDisplayNameSchema(ModelSchema):
    class Meta:
        model = UserRole
        fields = [
            "id",
            "name",
        ]


class UserRoleSchema(ModelSchema):
    class Meta:
        model = UserRole
        fields = [
            "id",
            "name",
            "permissions",
            "rules",
        ]
        optional_fields = "__all__"


# ----------------------------------------------------
# Filter Schemas
# ----------------------------------------------------


class UserRoleFilterSchema(FilterSchema):
    id: MultiValue(str, allow_null=False) = Field(
        None,
        q="id",
        title="Id",
        description="Comma-separated exact IDs.",
    )
    name: Optional[str] = Field(
        None,
        q="name",
        title="Name",
        description="Search extact name.",
    )

    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )

# ----------------------------------------------------
# Permission and Rules
# ----------------------------------------------------


class PermissionSchema(Schema):
    id: str = Field(description="Technical name of the permission (identifier).")
    name: str = Field(description="Title of the permission.")


class AccessRuleSchema(Schema):
    id: str
    name: str = Field(description="Title of the access rule.")
    description: Optional[str] = Field(description="Description of the access rules.")
