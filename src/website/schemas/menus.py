from typing import Optional

from django.db.models import Q
from pydantic import Field
from ulid import ULID

from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from website.models import Menu

from .pages import PageDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class MenuDisplayNameSchema(ModelSchema):
    """Declared first: `MenuSchema.parent` points back at this one."""

    class Meta:
        model = Menu
        fields = ["id", "name"]


class MenuSchema(ModelSchema):

    parent: Optional[MenuDisplayNameSchema] = None
    page: Optional[PageDisplayNameSchema] = None

    class Meta:
        model = Menu
        fields = [
            "id",
            "name",
            "parent",
            "parent_path",
            "sequence",
            "page",
            "link",
            "new_window",
            "create_date",
        ]
        optional_fields = "__all__"


class MenuCreateSchema(ModelSchema):
    class Meta:
        model = Menu
        fields = ["name", "parent", "sequence", "page", "link", "new_window"]


class MenuUpdateSchema(ModelSchema):
    class Meta:
        model = Menu
        fields = ["name", "parent", "sequence", "page", "link", "new_window"]
        optional_fields = "__all__"


# `parent_path` is readable but never writable: it is the materialized path,
# derived by `MenuQuerySet`. Note that `editable=False` on the field does *not*
# keep the schema factory from picking it up -- only the explicit `fields` list
# does. It is exposed on the response side because a client can rebuild the
# whole tree from it, and `MenuFilterSchema.root` filters on it.
#
# `Menu.url` is absent on purpose: it dereferences `self.page.slug`, a
# synchronous query that would raise `SynchronousOnlyOperation` if it ran while
# an async route serializes the response.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class MenuFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the name.",
    )
    parent: MultiValue(str) = Field(
        None,
        q="parent__id",
        title="Parent",
        description="Comma-separated identifiers of the direct parent items, `null` "
        "for the top-level items.",
    )
    # `ULID` rather than `str`: a malformed id is refused (422) instead of
    # silently matching nothing.
    root: Optional[ULID] = Field(
        None,
        title="Root",
        description="Identifier of an item: returns it and the whole subtree below it.",
    )
    # `target_page` and not `page`: the list route flattens every query
    # parameter into one signature, where `page` and `page_size` already belong
    # to `PageNumberPagination.Input`. A filter of that name makes ninja refuse
    # to build the operation at import time.
    target_page: MultiValue(str) = Field(
        None,
        q="page__id",
        title="Target Page",
        description="Comma-separated identifiers of the pages the item targets, `null` "
        "for the items targeting none.",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains", "link__icontains"],
        title="Search Term",
        description="Search term in the name or the target link.",
    )

    def filter_root(self, value):
        """The item and every item below it, at any depth.

        Not a `parent_path__startswith` on the pk: a path starts at the top of
        its tree, so an inner item is the prefix of nothing -- the bug
        `MenuService.read_tree` was fixed of, which reads the root's own path
        first. Here, a containment does it in one condition: a path is ULIDs of
        a fixed length joined by `/`, which a ULID never contains, so `"<pk>/"`
        only matches a whole segment. It does not use the prefix index of
        `parent_path`, which on a table of menus is no loss.
        """
        if not value:
            return Q()
        return Q(parent_path__contains=f"{value}/")
