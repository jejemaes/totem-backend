from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, ModelController, ResequenceModelControllerMixin
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from website.schemas import (
    MenuCreateSchema,
    MenuDisplayNameSchema,
    MenuFilterSchema,
    MenuSchema,
    MenuUpdateSchema,
)
from website.services import MenuService


class MenuController(
    TokenHasScopePermissionModelControllerMixin,
    DisplayNameModelControllerMixin,
    ResequenceModelControllerMixin,
    ModelController,
):
    api = api_v1
    service = MenuService

    path_prefix = "/website/menus/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.websitemenu.read"],
        "create": ["totem.websitemenu.create"],
        "update": ["totem.websitemenu.update"],
        "delete": ["totem.websitemenu.delete"],
        # Numbering menu items is updating them.
        "resequence": ["totem.websitemenu.update"],
        "display_name": ["totem.websitemenu.read"],
    }

    list_response_schema: Schema = List[MenuSchema]
    list_filter_schema: FilterSchema = MenuFilterSchema
    # `parent_path` is deliberately absent: it is readable, but ordering on it
    # is a tree traversal a client gets for free by sorting the paths itself.
    list_ordering_fields = [
        "name",
        "sequence",
        "create_date",
    ]
    list_ordering_default_fields = ["sequence", "name"]

    retrieve_response_schema: Schema = MenuSchema
    create_request_schema = MenuCreateSchema
    create_response_schema = MenuSchema
    update_request_schema = MenuUpdateSchema
    update_response_schema = MenuSchema
    display_name_response_schema = MenuDisplayNameSchema
