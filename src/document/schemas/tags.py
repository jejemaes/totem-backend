from typing import Optional

from pydantic import Field
from ulid import ULID

from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from document.models import DocumentTag

from .tag_categories import DocumentTagCategoryDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class DocumentTagDisplayNameSchema(ModelSchema):
    # The category carries the color the tag is shown with: a tag has none of
    # its own.
    category: DocumentTagCategoryDisplayNameSchema

    class Meta:
        model = DocumentTag
        fields = ["id", "name", "category"]


class DocumentTagSchema(ModelSchema):
    # Without the annotation the relation serializes to its bare pk, and is not
    # prefetched.
    category: Optional[DocumentTagCategoryDisplayNameSchema] = None

    class Meta:
        model = DocumentTag
        fields = ["id", "name", "category", "sequence"]
        optional_fields = "__all__"


class DocumentTagCreateSchema(ModelSchema):
    class Meta:
        model = DocumentTag
        fields = ["name", "category", "sequence"]
        optional_fields = ["sequence"]


class DocumentTagUpdateSchema(ModelSchema):
    class Meta:
        model = DocumentTag
        fields = ["name", "category", "sequence"]
        optional_fields = "__all__"


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class DocumentTagFilterSchema(FilterSchema):
    # `ULID` rather than `str`: a malformed id is refused (422) instead of
    # silently matching nothing.
    category: MultiValue(ULID, allow_null=False) = Field(
        None,
        q="category__id",
        title="Category",
        description="Comma-separated identifiers of the categories of the tags.",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )
