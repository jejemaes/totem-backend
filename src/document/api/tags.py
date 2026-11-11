from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import (
    DisplayNameModelControllerMixin,
    ModelController,
    ResequenceModelControllerMixin,
)
from document.schemas import (
    DocumentTagCreateSchema,
    DocumentTagDisplayNameSchema,
    DocumentTagFilterSchema,
    DocumentTagSchema,
    DocumentTagUpdateSchema,
)
from document.services import DocumentTagService
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin


class DocumentTagController(
    TokenHasScopePermissionModelControllerMixin,
    DisplayNameModelControllerMixin,
    ResequenceModelControllerMixin,
    ModelController,
):
    api = api_v1
    service = DocumentTagService

    path_prefix = "/document/tags/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.documenttag.read"],
        "create": ["totem.documenttag.create"],
        "update": ["totem.documenttag.update"],
        "delete": ["totem.documenttag.delete"],
        # Numbering the tags is updating them.
        "resequence": ["totem.documenttag.update"],
        "display_name": ["totem.documenttag.read"],
    }

    list_response_schema: Schema = List[DocumentTagSchema]
    list_filter_schema: FilterSchema = DocumentTagFilterSchema
    # Direct model fields only: by category (its pk), then within it.
    list_ordering_fields = ["category", "sequence", "name"]
    list_ordering_default_fields = ["category", "sequence", "name"]

    retrieve_response_schema: Schema = DocumentTagSchema
    create_request_schema = DocumentTagCreateSchema
    create_response_schema = DocumentTagSchema
    update_request_schema = DocumentTagUpdateSchema
    update_response_schema = DocumentTagSchema
    display_name_response_schema = DocumentTagDisplayNameSchema
