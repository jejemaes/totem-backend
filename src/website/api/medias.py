import typing as t
from typing import List

from ninja import FilterSchema, Path, Schema
from ninja.files import UploadedFile

from core.api import (
    BaseModelController,
    CreateModelControllerMixin,
    DeleteModelControllerMixin,
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
)
from core.services import ServiceValidationMultiError
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from website.schemas import (
    MediaCreateSchema,
    MediaListFilterSchema,
    MediaListSchema,
    MediaSchema,
)
from website.services import MediaService


class MediaController(
    TokenHasScopePermissionModelControllerMixin,
    CreateModelControllerMixin,
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
    DeleteModelControllerMixin,
    BaseModelController,
):
    """The only multipart controller in the project.

    Deliberately *not* a `ModelController`, and not for taste. That base drags
    in `UpdateModelControllerMixin`, whose `update` function already carries
    `MAGIC_ROUTE_ATTR` -- it is set on the shared function object by
    `UserController`, in an app autodiscovered before this one.
    `BaseController.add_routes_to` finds it through `inspect.getmembers` and
    then sorts by `list(cls.__dict__).index(name)`, which raises
    `ValueError: 'update' is not in list` AT IMPORT TIME, because nothing put it
    in this class' own `__dict__`. `CountryController` composes its mixins
    explicitly for the same reason.

    There is no update anyway: a media is immutable, see `MediaService`.

    A mixin whose route IS registered does not have that problem: registering
    goes through `method_to_route_function`, whose `view_wrapper` branch rebinds
    the annotated function onto this class -- which is exactly what puts the
    name in `cls.__dict__`. So `list` is safe here while `update` is not, and it
    would become unsafe again the moment `list_response_schema` went away.

    Note `DeleteModelControllerMixin` is inherited ON PURPOSE, with a scope. Its
    `add_routes_to` is guarded by `if cls.model:` alone -- unlike every other
    mixin it has no schema switch -- so inheriting it always registers the
    route, and `_get_action_permissions` returns `[]` for a missing
    `permission_map` key, which would leave DELETE open to any authenticated
    token. Deletion is wanted here (`CleanupFileQuerysetMixin.delete` is what
    reference-counts the filestore), so the key below is not optional.
    """

    api = api_v1
    service = MediaService

    path_prefix = "/website/medias/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.websitemedia.read"],
        "create": ["totem.websitemedia.create"],
        "delete": ["totem.websitemedia.delete"],
    }

    # Kept declared even though the body annotation is replaced below: it is
    # what keeps `CreateModelControllerMixin.add_routes_to` registering the
    # route with its 201 response and operation id, what keeps
    # `permission_map["create"]` wired onto it through
    # `_create_function_decorators`, and what keeps `validate_controllers`
    # checking the schema against `MediaService.create_schema` at startup --
    # none of which a hand-written `@route.post` would get.
    create_request_schema = MediaCreateSchema
    create_response_schema = MediaSchema
    retrieve_response_schema: Schema = MediaSchema

    # The library behind the editor's image picker. `MediaListSchema` rather
    # than `MediaSchema`: a picker needs a thumbnail, a caption and a mimetype,
    # and it is the one that normalises `content` to a public URL -- a list
    # response serialises `instance.__dict__`, which holds the bare stored path.
    list_response_schema: Schema = List[MediaListSchema]
    list_filter_schema: FilterSchema = MediaListFilterSchema
    # Direct model fields only: `queryset_order_by_fields` resolves each one with
    # `model._meta.get_field()`. `create_date` is orderable without being in the
    # response -- the picker never shows it, it just wants the newest first.
    list_ordering_fields = ["name", "create_date"]
    list_ordering_default_fields = ["-create_date"]

    @classmethod
    def _annotate_create_view_function(cls, view_func, path):
        """Multipart, not JSON.

        The generic version annotates `request_body` as
        `Annotated[create_request_schema, Body()]`. Annotating that same schema
        with `File()` instead does NOT work: ninja builds no
        `__ninja_flatten_map__` for the file source -- `_create_models` has a
        literal `pass` for it -- so `FileModel` hands `{"content": <file>}`
        straight to a model whose only field is `request_body`, and every
        request 422s on a missing field. The file has to be a parameter of its
        own, which means replacing the handler too (below).

        No `File(...)` marker is needed: ninja assigns one automatically to any
        `UploadedFile` annotation, in `_get_param_type`.
        """
        annotations = t.cast(t.Any, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        annotations["content"] = UploadedFile
        return view_func

    async def create(self, request, path_parameters, content):
        """Wraps the upload in the service's input schema by hand.

        The service extracts along `create_schema` and refuses a raw dict, so
        the file cannot simply be forwarded.

        Defining this here also takes the method out of the shared mutable
        `CreateModelControllerMixin.create`, whose `__annotations__` every
        controller's `_annotate_create_view_function` scribbles on.
        """
        try:
            instances = await request.env.get(self.service).create(
                [MediaCreateSchema(content=content)]
            )
            return instances[0] if instances else None
        except ServiceValidationMultiError as exc:
            # `["file"]`, not `["body", "request_body"]`: the payload is a
            # multipart file part, and ninja locates its own errors for this
            # route under `("file",) + ...`. Both shapes therefore end in
            # `content`, which is the field name the client sent and the one its
            # error handling reads.
            raise self.service_validation_error_to_api_error(
                exc, self.create_response_schema, loc_path=["file"]
            )
