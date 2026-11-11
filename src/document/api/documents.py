import typing as t
from typing import List

from ninja import File, FilterSchema, Form, Path, Schema
from ninja.errors import ValidationError
from ninja.files import UploadedFile

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, ModelController, route
from core.services import ServiceValidationMultiError
from document.schemas import (
    DocumentCreateFormSchema,
    DocumentCreateSchema,
    DocumentDisplayNameSchema,
    DocumentFilterSchema,
    DocumentSchema,
    DocumentUpdateSchema,
    DocumentUploadFormSchema,
)
from document.services import DocumentService
from totem.api import api_v1
from user.security import TokenHasScopePermission, TokenHasScopePermissionModelControllerMixin


class DocumentController(
    TokenHasScopePermissionModelControllerMixin, DisplayNameModelControllerMixin, ModelController
):
    """All five operations, so a `ModelController`: the import-time trap that
    makes `MediaController` compose its mixins by hand is an `update` inherited
    without its route, and here the update is wanted and declared.

    The creation is `multipart/form-data`, for both types: the form fields of
    `DocumentCreateFormSchema` plus a `file` part, which a text leaves out. One
    content type per route, so a text is posted as a form too rather than as
    JSON. The update is JSON: nothing it changes is a file.
    """

    api = api_v1
    service = DocumentService

    path_prefix = "/document/documents/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.document.read"],
        "create": ["totem.document.create"],
        "update": ["totem.document.update"],
        # Not optional: without it DELETE would be open to any authenticated
        # token, see `MediaController`.
        "delete": ["totem.document.delete"],
        "display_name": ["totem.document.read"],
    }

    list_response_schema: Schema = List[DocumentSchema]
    list_filter_schema: FilterSchema = DocumentFilterSchema
    list_ordering_fields = ["name", "date", "size", "mimetype", "create_date", "update_date"]
    list_ordering_default_fields = ["-create_date"]

    retrieve_response_schema: Schema = DocumentSchema
    # Kept declared although the create body is replaced below: it registers the
    # route with its 201 and its scope, and `validate_controllers` checks it
    # against `DocumentService.create_schema`; see `MediaController`.
    create_request_schema = DocumentCreateSchema
    create_response_schema = DocumentSchema
    update_request_schema = DocumentUpdateSchema
    update_response_schema = DocumentSchema
    display_name_response_schema = DocumentDisplayNameSchema

    # Actions

    # Written in the class body, so registered before `/{id}/` (see
    # `BaseController.add_routes_to`); a POST would not collide anyway.
    @route.post(
        "/upload/",
        response={201: List[DocumentSchema]},
        permissions=[TokenHasScopePermission(["totem.document.create"])],
        operation_id="documentUpload",
        summary="Upload Documents",
        tags=["Document"],
    )
    async def upload(
        self,
        request,
        files: File[List[UploadedFile]],
        form: Form[DocumentUploadFormSchema],
    ):
        """One `file` document per file part, all or nothing; see
        `DocumentService.upload`."""
        service = request.env.get(self.service)
        try:
            instances = await service.upload(files, tags=form.tags, user=form.user, contact=form.contact)
        except ServiceValidationMultiError as exc:
            # Located where ninja puts its own errors on this request: a file
            # under `("file", "files")`, the shared values under `("form",
            # <field>)`. The position of the file refused is the `ctx.key`.
            raise self._multipart_error(
                self.service_validation_error_to_api_error(exc, None, loc_path=[], fields_map={"file": "files"}),
                file_fields={"files"},
            )
        # Refetched, for the same reason as a creation: see
        # `CreateModelControllerMixin.create`.
        pks = [instance.pk for instance in instances]
        queryset = service.apply_query_fields(
            service.get_queryset().filter(pk__in=pks),
            self._response_orm_fields(DocumentSchema),
        )
        by_pk = {instance.pk: instance async for instance in queryset}
        return 201, [by_pk[pk] for pk in pks]

    # Create, multipart

    @classmethod
    def _annotate_create_view_function(cls, view_func, path):
        """The form fields and the file, each a parameter of its own: annotating
        the whole create schema with `File()` or `Form()` does not work, see
        `MediaController._annotate_create_view_function`."""
        annotations = t.cast(t.Any, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        annotations["request_body"] = t.Annotated[DocumentCreateFormSchema, Form()]
        annotations["file"] = t.Annotated[t.Optional[UploadedFile], File(None)]
        return view_func

    async def create(self, request, path_parameters, request_body, file=None):
        # Only the fields the form set: `create` fills the others from its
        # defaults, as for a JSON body.
        values = {name: getattr(request_body, name) for name in request_body.model_fields_set}
        request_body = DocumentCreateSchema(**values, file=file)
        try:
            return await super().create(request, path_parameters, request_body)
        except ValidationError as error:
            # Located for a JSON body by the generic route: moved where ninja
            # puts its own errors on this multipart request.
            for detail in error.errors:
                detail["loc"] = detail["loc"][2:]
            raise self._multipart_error(error, file_fields={"file"})

    @staticmethod
    def _multipart_error(error, file_fields):
        """`error`, whose `loc`s are bare field names, located as ninja locates
        its own errors on a multipart request: a file part under `"file"`, any
        other field under `"form"`. One shape for both kinds of error, so a
        client reads the last element of `loc` as the field it sent."""
        for detail in error.errors:
            detail["loc"] = ["file" if detail["loc"][0] in file_fields else "form"] + detail["loc"]
        return error
