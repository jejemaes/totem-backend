import typing as t
from typing import List

from ninja import File, FilterSchema, Form, Path, Schema
from ninja.errors import ValidationError
from ninja.files import UploadedFile

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, GroupByModelControllerMixin, ModelController
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from account.schemas import (
    InvoiceCreateFormSchema,
    InvoiceCreateSchema,
    InvoiceDisplayNameSchema,
    InvoiceFilterSchema,
    InvoiceSchema,
    InvoiceUpdateSchema,
)
from account.services import InvoiceService


class InvoiceController(
    TokenHasScopePermissionModelControllerMixin,
    DisplayNameModelControllerMixin,
    GroupByModelControllerMixin,
    ModelController,
):
    """The creation is `multipart/form-data`, as for a document: the form fields
    of `InvoiceCreateFormSchema` plus an optional `file_content` part. The update
    is JSON: the file cannot change."""

    api = api_v1
    service = InvoiceService

    path_prefix = "/accounting/invoices/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.invoice.read"],
        "create": ["totem.invoice.create"],
        "update": ["totem.invoice.update"],
        "delete": ["totem.invoice.delete"],
        "display_name": ["totem.invoice.read"],
        "group_by": ["totem.invoice.read"],
    }

    list_response_schema: Schema = List[InvoiceSchema]
    list_filter_schema: FilterSchema = InvoiceFilterSchema
    list_ordering_fields = ["number", "date", "due_date", "amount_total", "create_date"]
    list_ordering_default_fields = ["-date", "-number"]

    retrieve_response_schema: Schema = InvoiceSchema
    # Kept declared although the create body is replaced below; see
    # `DocumentController`.
    create_request_schema = InvoiceCreateSchema
    create_response_schema = InvoiceSchema
    update_request_schema = InvoiceUpdateSchema
    update_response_schema = InvoiceSchema
    display_name_response_schema = InvoiceDisplayNameSchema

    # Create, multipart

    @classmethod
    def _annotate_create_view_function(cls, view_func, path):
        """The form fields and the file, each a parameter of its own; see
        `DocumentController._annotate_create_view_function`."""
        annotations = t.cast(t.Any, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        annotations["request_body"] = t.Annotated[InvoiceCreateFormSchema, Form()]
        annotations["file_content"] = t.Annotated[t.Optional[UploadedFile], File(None)]
        return view_func

    async def create(self, request, path_parameters, request_body, file_content=None):
        values = {name: getattr(request_body, name) for name in request_body.model_fields_set}
        request_body = InvoiceCreateSchema(**values, file_content=file_content)
        try:
            return await super().create(request, path_parameters, request_body)
        except ValidationError as error:
            # Located for a JSON body by the generic route: moved where ninja puts
            # its own errors on a multipart request, as `DocumentController.create`.
            for detail in error.errors:
                detail["loc"] = detail["loc"][2:]
                detail["loc"] = ["file" if detail["loc"][0] == "file_content" else "form"] + detail["loc"]
            raise error
