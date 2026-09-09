"""Schemas for the HTML widget listing.

Not a `ModelSchema`: a widget has no database row. The registry in
`core.html_widget` is the source of truth, and each marker carries its own
parameters inline.
"""

import typing as t

from ninja import Schema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class HtmlWidgetSchema(Schema):
    id: str
    title: str

    # JSON Schema of the widget's parameters, straight out of
    # `attribute_schema.model_json_schema()`. The editor builds its options form
    # from this instead of restating every widget's parameters in javascript.
    #
    # Named after the widget attribute it comes from, and not `schema`: a
    # pydantic field called `schema` shadows an attribute of `Schema` itself and
    # earns a warning for it.
    attribute_schema: t.Dict[str, t.Any]
