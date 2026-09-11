from typing import Optional

from ninja import Schema

from core.schemas import ModelSchema
from website.models import Website
from website.schemas.menus import MenuDisplayNameSchema
from website.schemas.pages import PageDisplayNameSchema


class WebsitePathParam(Schema):
    """The pk of the singleton, for the `/current/` aliases.

    Same shape and same purpose as `user.schemas.ProfilePathParam`: the caller
    does not know the id, so the route resolves it and hands it to the generated
    `update`, which is addressed by path. `str` and not `UUID4`, unlike the user
    one -- `Website.id` is a `ULIDField`, a 26-character `CharField`.
    """

    id: str


# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class WebsiteSchema(ModelSchema):

    # Without these annotations the relations serialize to their bare primary
    # key, and they are also what drives the prefetching -- see
    # `website.schemas.pages`.
    menu: Optional[MenuDisplayNameSchema] = None
    homepage: Optional[PageDisplayNameSchema] = None

    class Meta:
        model = Website
        fields = [
            "id",
            "name",
            "headline",
            "meta_authors",
            "meta_description",
            "menu",
            "homepage",
            "footer",
            "side_bar_content",
            "theme",
            "theme_options",
        ]
        optional_fields = "__all__"


class WebsiteUpdateSchema(ModelSchema):
    class Meta:
        model = Website
        fields = [
            "name",
            "headline",
            "meta_authors",
            "meta_description",
            "menu",
            "homepage",
            "footer",
            "side_bar_content",
            "theme",
            "theme_options",
        ]
        optional_fields = "__all__"


# No create schema, no delete, and no filter or list schema: `WebsiteService`
# exposes neither `create` nor `delete` (the row is provisioned once by
# `WebsiteConfig.populate_system`), and a paginated list of a single row is not
# a contract worth publishing. No display-name schema either -- nothing points
# a relation at `Website`.
#
# `footer` is writable, and is the one field here that carries widget markers:
# `HtmlField(allow_widget=True)` validates them at write time, so a marker
# naming an unregistered widget is refused by the field's own validator.
#
# `theme_options` sits in `Meta.fields` like anything else, and is worth a note
# only because it could not until recently: `core.schemas.fields` registered its
# JSON converter on the postgres contrib subclass, so the `models.JSONField`
# every model declares resolved to no converter at all and raised
# `ImproperlyConfigured` while this class was being built. It converts to
# `AnyObject` -- deliberately not a `Dict[str, Any]` declared by hand -- because
# the shape a theme accepts is its `option_schema`'s business, exposed through
# `/website/themes/`, and restating a narrower shape here would be a second
# description of it to keep in sync.
