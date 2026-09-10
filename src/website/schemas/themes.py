"""Schemas for the theme catalogue and the layout vocabulary.

Not `ModelSchema`s: a theme has no database row, and a layout id is a module
constant. `website.theme` is the source of truth for both, and only the
selection is stored -- on `Website.theme` and `Page.layout`.
"""

import typing as t

from ninja import Schema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class LayoutSchema(Schema):
    id: str
    title: str


class ThemeSchema(Schema):
    id: str
    title: str

    # Which of the shared layout ids this theme implements. A page may still
    # choose one that is absent from this list -- it falls back when it renders
    # -- so this is what an editor offers, not what it must restrict to.
    layouts: t.List[str]

    # JSON Schema of the theme's options, straight out of
    # `option_schema.model_json_schema()`. Same job as
    # `HtmlWidgetSchema.attribute_schema`: the editor builds its settings form
    # from this instead of restating every theme's options in javascript.
    #
    # Named after the theme attribute and not `schema`, which would shadow an
    # attribute of `Schema` itself.
    option_schema: t.Dict[str, t.Any]
