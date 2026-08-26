from typing import List, Optional

from ninja import FilterSchema
from pydantic import Field

from base.schemas import CountryDisplayNameSchema
from core.schemas import ModelSchema
from contact.models import Contact

from .contact_tags import ContactTagDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

ADDRESS_FIELDS = ["number", "street", "zip", "city", "country"]


class ContactSchema(ModelSchema):

    # Without these annotations a relation serializes to its bare primary key.
    # They also drive the prefetching: `extract_orm_fields_map` walks into the
    # sub-schema and `queryset_fetch_fields` turns it into a `Prefetch`, which an
    # async route needs to serialize outside of any `sync_to_async`.
    country: Optional[CountryDisplayNameSchema] = None
    tags: Optional[List[ContactTagDisplayNameSchema]] = None

    class Meta:
        model = Contact
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "mobile",
            "birth_date",
            *ADDRESS_FIELDS,
            "tags",
            "create_date",
            "update_date",
        ]
        optional_fields = "__all__"


class ContactCreateSchema(ModelSchema):
    class Meta:
        model = Contact
        fields = [
            "first_name",
            "last_name",
            "email",
            "mobile",
            "birth_date",
            *ADDRESS_FIELDS,
            "tags",
        ]


class ContactUpdateSchema(ModelSchema):
    class Meta:
        model = Contact
        fields = [
            "first_name",
            "last_name",
            "email",
            "mobile",
            "birth_date",
            *ADDRESS_FIELDS,
            "tags",
        ]
        optional_fields = "__all__"


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class ContactFilterSchema(FilterSchema):
    email: Optional[str] = Field(
        None,
        q="email__icontains",
        title="Email",
        description="Search term in the email.",
    )
    city: Optional[str] = Field(
        None,
        q="city__icontains",
        title="City",
        description="Search term in the city.",
    )
    country: Optional[str] = Field(
        None,
        q="country__code",
        title="Country",
        description="ISO 3166-1 alpha-2 code of the country.",
    )
    tag: Optional[str] = Field(
        None,
        q="tags__id",
        title="Tag",
        description="Identifier of a tag the contact must carry.",
    )
    search: Optional[str] = Field(
        None,
        q=["first_name__icontains", "last_name__icontains", "email__icontains"],
        title="Search Term",
        description="Search term in the first name, the last name or the email.",
    )
