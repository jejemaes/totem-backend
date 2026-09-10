from ninja import Schema
from ninja.errors import HttpError

from core.api import (
    BaseModelController,
    RetrieveModelControllerMixin,
    UpdateModelControllerMixin,
    route,
)
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import (
    TokenHasScopePermission,
    TokenHasScopePermissionModelControllerMixin,
)
from website.schemas import WebsitePathParam, WebsiteSchema, WebsiteUpdateSchema
from website.services import WebsiteService


class WebsiteController(
    TokenHasScopePermissionModelControllerMixin,
    RetrieveModelControllerMixin,
    UpdateModelControllerMixin,
    BaseModelController,
):
    """The site's own settings: name, headline, SEO meta, main menu, homepage, footer.

    Until this controller existed there was no way to read or write any of them
    over the API -- `Website` had no service and no route, and the public views
    reached it straight through the ORM.

    Deliberately *not* a `ModelController`, for the reason `MediaController`
    documents at length: that base drags in `DeleteModelControllerMixin`, whose
    `add_routes_to` is guarded by `if cls.model:` alone with no schema switch, so
    inheriting it ALWAYS registers `DELETE /{id}/` -- and
    `_get_action_permissions` returns `[]` for a key missing from
    `permission_map`, which would leave the site's settings deletable by any
    authenticated token. For a singleton that is disqualifying. `CreateMixin`
    and `ListModelControllerMixin` are left out too: the row is provisioned by
    `populate_system`, and a paginated list of one row is not a contract worth
    publishing.

    The two mixins that ARE inherited both register their route, which is what
    makes inheriting them safe: registration goes through
    `method_to_route_function`, whose `view_wrapper` branch rebinds the
    annotated function onto this class and so puts the name in `cls.__dict__` --
    without which `BaseController.add_routes_to`'s
    `list(cls.__dict__).index(name)` sort raises `ValueError` at import time.
    Dropping `retrieve_response_schema` or `update_request_schema` would
    therefore not merely remove a route, it would break the import.
    """

    api = api_v1
    service = WebsiteService

    path_prefix = "/website/websites/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.website.read"],
        "update": ["totem.website.update"],
    }

    retrieve_response_schema: Schema = WebsiteSchema
    update_request_schema = WebsiteUpdateSchema
    update_response_schema = WebsiteSchema

    # Actions

    # `/current/` because a client has no way to know the id: the row is a
    # singleton provisioned under a fixed pk. Same answer as
    # `UserController.profile_read`'s `/me/`, and it works for the same
    # structural reason -- these two are in `cls.__dict__` from the class body,
    # while `retrieve` and `update` are only put there later by
    # `method_to_route_function`, so they sort first and win the path match
    # against `/{id}/`.
    #
    # Permissions go on the route because
    # `TokenHasScopePermissionModelControllerMixin` only decorates the generated
    # CRUD views, exactly as `UserController.profile_read` carries
    # `IsAuthenticated` inline.

    @route.get(
        "/current/",
        response=WebsiteSchema,
        permissions=[TokenHasScopePermission(["totem.website.read"])],
        operation_id="websiteCurrentRead",
        summary="Read Current Website",
        tags=["Website"],
    )
    async def current_read(self, request):
        website = await request.env.get(self.service).read_current(
            fields=self._response_orm_fields(self.retrieve_response_schema)
        )
        if website is None:
            raise HttpError(status_code=404, message="Website not found.")
        return website

    @route.patch(
        "/current/",
        response=WebsiteSchema,
        permissions=[TokenHasScopePermission(["totem.website.update"])],
        operation_id="websiteCurrentUpdate",
        summary="Update Current Website",
        tags=["Website"],
    )
    async def current_update(self, request, request_body: WebsiteUpdateSchema):
        # The pk is resolved first and then handed to the generated `update`,
        # rather than calling the service with empty filters: `update({})` means
        # "every row", which is a landmine the day a second row exists. Only the
        # pk is loaded -- the response fields are fetched by `update` itself.
        website = await request.env.get(self.service).read_current(fields=["id"])
        if website is None:
            raise HttpError(status_code=404, message="Website not found.")
        return await self.update(
            request, WebsitePathParam(id=website.pk), request_body
        )
