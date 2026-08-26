from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from contact.schemas import (
    ContactTagCreateSchema,
    ContactTagFilterSchema,
    ContactTagSchema,
    ContactTagUpdateSchema,
)
from contact.services import ContactTagService


class ContactTagController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = ContactTagService

    path_prefix = "/contact-tags/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.contacttag.read"],
        "create": ["totem.contacttag.create"],
        "update": ["totem.contacttag.update"],
        "delete": ["totem.contacttag.delete"],
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
