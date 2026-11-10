from typing import Optional

from pydantic import Field

from core.api.filters import FilterSchema
from core.schemas import ModelSchema
from document.models import DocumentTagCategory

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class DocumentTagCategoryDisplayNameSchema(ModelSchema):
    class Meta:
        model = DocumentTagCategory
        fields = ["id", "name", "color"]


class DocumentTagCategorySchema(ModelSchema):
    class Meta:
        model = DocumentTagCategory
        fields = ["id", "name", "sequence", "color"]
        optional_fields = "__all__"


class DocumentTagCategoryCreateSchema(ModelSchema):
    class Meta:
        model = DocumentTagCategory
        fields = ["name", "sequence", "color"]
        optional_fields = ["sequence", "color"]


class DocumentTagCategoryUpdateSchema(ModelSchema):
    class Meta:
        model = DocumentTagCategory
        fields = ["name", "sequence", "color"]
        optional_fields = "__all__"


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class DocumentTagCategoryFilterSchema(FilterSchema):
    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )
