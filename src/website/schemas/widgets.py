from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from website.models import Widget

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class WidgetDisplayNameSchema(ModelSchema):
    class Meta:
        model = Widget
        fields = ["id", "title"]


class WidgetSchema(ModelSchema):
    class Meta:
        model = Widget
        fields = [
            "id",
            "title",
            "widget_type",
            "position",
            "param_content",
            "param_limit_item",
        ]
        optional_fields = "__all__"


class WidgetCreateSchema(ModelSchema):
    class Meta:
        model = Widget
        fields = [
            "title",
            "widget_type",
            "position",
            "param_content",
            "param_limit_item",
        ]


class WidgetUpdateSchema(ModelSchema):
    class Meta:
        model = Widget
        fields = [
            "title",
            "widget_type",
            "position",
            "param_content",
            "param_limit_item",
        ]
        optional_fields = "__all__"


# `rendered_content` is absent from the response schemas: it renders a template,
# and a widget type's render context may read the database -- a synchronous
# query in the middle of serialization.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class WidgetFilterSchema(FilterSchema):
    # Typed as plain strings rather than the model enums: a filter that does not
    # match anything is an empty result, not a validation error.
    widget_type: Optional[str] = Field(
        None,
        q="widget_type",
        title="Type",
        description="Exact widget type.",
    )
    position: Optional[str] = Field(
        None,
        q="position",
        title="Position",
        description="Exact position on the website.",
    )
    position_prefix: Optional[str] = Field(
        None,
        q="position__startswith",
        title="Position Prefix",
        description="Prefix of the position, to select a whole area (`FOOTER_`, `HOMEPAGE_`).",
    )
    search: Optional[str] = Field(
        None,
        q=["title__icontains"],
        title="Search Term",
        description="Search term in the title.",
    )
