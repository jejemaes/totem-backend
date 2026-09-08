from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from website.schemas import (
    MenuCreateSchema,
    MenuFilterSchema,
    MenuSchema,
    MenuUpdateSchema,
)
from website.services import MenuService


class MenuController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = MenuService

    path_prefix = "/website/menus/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.websitemenu.read"],
        "create": ["totem.websitemenu.create"],
        "update": ["totem.websitemenu.update"],
        "delete": ["totem.websitemenu.delete"],
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
