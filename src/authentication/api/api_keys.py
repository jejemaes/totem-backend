from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from authentication.schemas import (
    ApiKeyCreatedSchema,
    ApiKeyCreateSchema,
    ApiKeyFilterSchema,
    ApiKeySchema,
)
from authentication.services import ApiKeyService
from core.api import (
    BaseModelController,
    CreateModelControllerMixin,
    DeleteModelControllerMixin,
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
)
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin

__all__ = ["ApiKeyController"]


class ApiKeyController(
    TokenHasScopePermissionModelControllerMixin,
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
    CreateModelControllerMixin,
    DeleteModelControllerMixin,
    BaseModelController,
):
    """ The machine-to-machine keys of the tenant.

    Deliberately not a `ModelController`, for the two reasons `MediaController`
    spells out at length: that base drags in `UpdateModelControllerMixin`, whose
    `update` function already carries `MAGIC_ROUTE_ATTR` from another app's
    controller and would raise `ValueError` at import time here; and there is no
    update anyway -- a secret is replaced, not edited (see `ApiKeyService`).

    Note `DeleteModelControllerMixin` registers its route on `cls.model` alone,
    with no schema switch, and `_get_action_permissions` returns `[]` for a
    missing key -- so the `"delete"` key below is what stands between DELETE and
    any authenticated token. Same for `"create"`.

    A key may be managed with a user's token, and also with another key -- the
    authenticators are both accepted here, as everywhere. What a key cannot do is
    manage keys: `totem.apikey.*` is registered `is_public=False`, so it is absent
    from the choices of `ApiKey.scope` and no key can ever hold it.
    """

    api = api_v1
    service = ApiKeyService

    path_prefix = "/api-keys/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.apikey.read"],
        "create": ["totem.apikey.create"],
        "delete": ["totem.apikey.delete"],
    }

    list_response_schema: Schema = List[ApiKeySchema]
    list_filter_schema: FilterSchema = ApiKeyFilterSchema
    list_ordering_fields = ["name", "created_at", "is_active"]
    list_ordering_default_fields = ["name"]

    retrieve_response_schema: Schema = ApiKeySchema

    create_request_schema = ApiKeyCreateSchema
    # The one response in the project that carries a clear credential, and the
    # only moment the secret exists: see `ApiKeyCreatedSchema`.
    create_response_schema = ApiKeyCreatedSchema

    async def create(self, request, path_parameters, request_body):
        """ The creation, plus the one value the refetch cannot bring back.

        `CreateModelControllerMixin.create` reloads the record from the database
        before serializing it, deliberately: a response then reads what the
        database derived rather than what was written. The clear secret is the one
        value the database does not hold -- only its SHA-256 -- so it does not
        survive that reload and has to be carried across, from the service that
        minted it.

        Overriding rather than hand-writing a `@route.post`: the mixin is what
        registers the 201 and the operation id, wires `permission_map["create"]`
        onto the route, and has `validate_controllers` check the schemas against
        the service at startup. `method_to_route_function` builds the route from
        `cls.create`, so this override is what the route runs.
        """
        instance = await super().create(request, path_parameters, request_body)
        if instance is not None:
            instance.secret = request.env.get(self.service).minted_secret(instance.pk)
        return instance
