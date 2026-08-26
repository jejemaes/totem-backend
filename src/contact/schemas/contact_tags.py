from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from contact.models import ContactTag

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class ContactTagDisplayNameSchema(ModelSchema):
    class Meta:
        model = ContactTag
        fields = ["id", "name", "color"]


class ContactTagSchema(ModelSchema):
    class Meta:
        model = ContactTag
        fields = ["id", "name", "color"]
        optional_fields = "__all__"


class ContactTagCreateSchema(ModelSchema):
    class Meta:
        model = ContactTag
        fields = ["name", "color"]


class ContactTagUpdateSchema(ModelSchema):
    class Meta:
        model = ContactTag
        fields = ["name", "color"]
        optional_fields = "__all__"


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class ContactTagFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the tag name.",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the tag name.",
    )
