from typing import Optional

from ninja import FilterSchema, Schema
from pydantic import Field

from core.schemas import ModelSchema
from base.models import Country

# ----------------------------------------------------
# Path Schemas
# ----------------------------------------------------


class CountryPathParam(Schema):
    """The retrieve route is `/{id}/`, but the primary key of a country is its
    ISO `code`. The alias maps the path parameter onto the ORM field name, which
    is what `RetrieveModelControllerMixin.retrieve` filters on.
    """

    code: str = Field(..., alias="id")


# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class CountryDisplayNameSchema(ModelSchema):
    class Meta:
        model = Country
        fields = ["code", "name"]
        extra_fields_kwargs = {
            # The code is the primary key: expose it as `id` so a country reads like
            # every other display-name schema, and a client always has an `id` to use
            # as the value of a select.
            "code": {"alias": "id"},
        }


class CountrySchema(ModelSchema):
    class Meta:
        model = Country
        fields = ["code", "name"]
        optional_fields = "__all__"
        extra_fields_kwargs = {
            "code": {"alias": "id"},
        }


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class CountryFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the country name.",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains", "code__icontains"],
        title="Search Term",
        description="Search term in the country name or in the ISO code.",
    )
