from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, ModelController
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from contact.schemas import (
    ContactTagCreateSchema,
    ContactTagDisplayNameSchema,
    ContactTagFilterSchema,
    ContactTagSchema,
    ContactTagUpdateSchema,
)
from contact.services import ContactTagService


class ContactTagController(
    TokenHasScopePermissionModelControllerMixin, DisplayNameModelControllerMixin, ModelController
):
    api = api_v1
    service = ContactTagService

    path_prefix = "/contact-tags/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.contacttag.read"],
        "create": ["totem.contacttag.create"],
        "update": ["totem.contacttag.update"],
        "delete": ["totem.contacttag.delete"],
        "display_name": ["totem.contacttag.read"],
    }

    list_response_schema: Schema = List[ContactTagSchema]
    list_filter_schema: FilterSchema = ContactTagFilterSchema
    list_ordering_fields = [
        "name",
        "color",
    ]
    list_ordering_default_fields = ["name"]

    retrieve_response_schema: Schema = ContactTagSchema
    create_request_schema = ContactTagCreateSchema
    create_response_schema = ContactTagSchema
    update_request_schema = ContactTagUpdateSchema
    update_response_schema = ContactTagSchema
    display_name_response_schema = ContactTagDisplayNameSchema
