from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from website.schemas import (
    PageCreateSchema,
    PageFilterSchema,
    PageSchema,
    PageUpdateSchema,
)
from website.services import PageService


class PageController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = PageService

    path_prefix = "/website/pages/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.websitepage.read"],
        "create": ["totem.websitepage.create"],
        "update": ["totem.websitepage.update"],
        "delete": ["totem.websitepage.delete"],
    }

    list_response_schema: Schema = List[PageSchema]
    list_filter_schema: FilterSchema = PageFilterSchema
    # Direct model fields only: `queryset_order_by_fields` resolves each one with
    # `model._meta.get_field()`, which a related lookup would not survive.
    list_ordering_fields = [
        "title",
        "slug",
        "is_published",
        "date_published",
        "update_date",
        "layout",
    ]
    list_ordering_default_fields = ["title"]

    retrieve_response_schema: Schema = PageSchema
    create_request_schema = PageCreateSchema
    create_response_schema = PageSchema
    update_request_schema = PageUpdateSchema
    update_response_schema = PageSchema
