from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from user.schemas import UserDisplayNameSchema
from website.models import Page

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class PageDisplayNameSchema(ModelSchema):
    class Meta:
        model = Page
        fields = ["id", "title", "slug"]


class PageSchema(ModelSchema):

    # Without this annotation the relation serializes to its bare primary key.
    # It also drives the prefetching, see `contact.schemas.contacts`.
    user: Optional[UserDisplayNameSchema] = None

    class Meta:
        model = Page
        fields = [
            "id",
            "title",
            "slug",
            "content",
            "is_published",
            "date_published",
            "update_date",
            "user",
            "layout",
        ]
        optional_fields = "__all__"


class PageCreateSchema(ModelSchema):
    class Meta:
        model = Page
        fields = ["title", "slug", "content", "is_published", "user", "layout"]


class PageUpdateSchema(ModelSchema):
    class Meta:
        model = Page
        fields = ["title", "slug", "content", "is_published", "user", "layout"]
        optional_fields = "__all__"


# `date_published` and `update_date` are deliberately absent from both write
# schemas: they are derived by `PageQuerySet`, never given by a caller. The
# `url` property is absent from the response schemas too -- `apply_query_fields`
# resolves every requested lookup through `model._meta.get_field()`, so a
# non-ORM name there would break any client passing `?fields=`.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class PageFilterSchema(FilterSchema):
    title: Optional[str] = Field(
        None,
        q="title__icontains",
        title="Title",
        description="Search term in the title.",
    )
    slug: Optional[str] = Field(
        None,
        q="slug",
        title="Slug",
        description="Exact slug of the page, which identifies it in the URL.",
    )
    is_published: Optional[bool] = Field(
        None,
        q="is_published",
        title="Is Published",
        description="Publication state of the page.",
    )
    author: Optional[str] = Field(
        None,
        q="user__id",
        title="Author",
        description="Identifier of the author of the page.",
    )
    layout: Optional[str] = Field(
        None,
        q="layout",
        title="Layout",
        description="Exact layout identifier of the page.",
    )
    search: Optional[str] = Field(
        None,
        q=["title__icontains", "slug__icontains"],
        title="Search Term",
        description="Search term in the title or the slug.",
    )
