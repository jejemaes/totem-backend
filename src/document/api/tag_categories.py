from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import (
    DisplayNameModelControllerMixin,
    ModelController,
    ResequenceModelControllerMixin,
)
from document.schemas import (
    DocumentTagCategoryCreateSchema,
    DocumentTagCategoryDisplayNameSchema,
    DocumentTagCategoryFilterSchema,
    DocumentTagCategorySchema,
    DocumentTagCategoryUpdateSchema,
)
from document.services import DocumentTagCategoryService
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin


class DocumentTagCategoryController(
    TokenHasScopePermissionModelControllerMixin,
    DisplayNameModelControllerMixin,
    ResequenceModelControllerMixin,
    ModelController,
):
    api = api_v1
    service = DocumentTagCategoryService

    path_prefix = "/document/tag-categories/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.documenttagcategory.read"],
        "create": ["totem.documenttagcategory.create"],
        "update": ["totem.documenttagcategory.update"],
        "delete": ["totem.documenttagcategory.delete"],
        # Numbering the categories is updating them.
        "resequence": ["totem.documenttagcategory.update"],
        "display_name": ["totem.documenttagcategory.read"],
    }

    list_response_schema: Schema = List[DocumentTagCategorySchema]
    list_filter_schema: FilterSchema = DocumentTagCategoryFilterSchema
    list_ordering_fields = ["sequence", "name", "color"]
    list_ordering_default_fields = ["sequence", "name"]

    retrieve_response_schema: Schema = DocumentTagCategorySchema
    create_request_schema = DocumentTagCategoryCreateSchema
    create_response_schema = DocumentTagCategorySchema
    update_request_schema = DocumentTagCategoryUpdateSchema
    update_response_schema = DocumentTagCategorySchema
    display_name_response_schema = DocumentTagCategoryDisplayNameSchema
