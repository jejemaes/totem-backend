from typing import List

from ninja import FilterSchema, Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from contact.schemas import (
    ContactCreateSchema,
    ContactFilterSchema,
    ContactSchema,
    ContactUpdateSchema,
)
from contact.services import ContactService


class ContactController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = ContactService

    path_prefix = "/contacts/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.contact.read"],
        "create": ["totem.contact.create"],
        "update": ["totem.contact.update"],
        "delete": ["totem.contact.delete"],
    }

    list_response_schema: Schema = List[ContactSchema]
    list_filter_schema: FilterSchema = ContactFilterSchema
    # Direct model fields only: `queryset_order_by_fields` resolves each one with
    # `model._meta.get_field()`, which a related lookup would not survive.
    list_ordering_fields = [
        "last_name",
        "first_name",
        "email",
        "city",
        "zip",
        "birth_date",
        "create_date",
        "update_date",
    ]
    list_ordering_default_fields = ["last_name", "first_name"]

    retrieve_response_schema: Schema = ContactSchema
    create_request_schema = ContactCreateSchema
    create_response_schema = ContactSchema
    update_request_schema = ContactUpdateSchema
    update_response_schema = ContactSchema
