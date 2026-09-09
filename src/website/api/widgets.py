from typing import List

from core.api import BaseController, route
from core.html_widget import get_widgets
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermission
from website.schemas import HtmlWidgetSchema


class HtmlWidgetController(BaseController):
    """The blocks an author can drop into website content, and their parameters.

    Deliberately not a `ModelController`, and the only controller in the project
    with neither a model nor a service: a widget has no database row. The
    registry in `core.html_widget` is the source of truth, filled at startup by
    `autodiscover_modules('html_widget')`, and each marker carries its own
    parameters inline. `validate_controllers` skips a controller whose `model`
    is None, so nothing at startup expects otherwise.

    It lives under `/website/` even though the registry is core-level, because
    what it lists is what may go into *website* content: the fields opting in
    with `allow_widget` are `Page.content` and `Website.footer`. A widget
    contributed by another app would still be listed here -- the registry is
    global -- which is the intended behaviour, not an oversight.

    Permissions go on the route rather than through
    `TokenHasScopePermissionModelControllerMixin`: that mixin maps CRUD
    operations to scopes via `permission_map`, and there is no CRUD operation
    here to map.
    """

    api = api_v1
    path_prefix = "/website/widgets/"
    auth = [OAuthTokenAuthentication()]

    @route.get(
        "/",
        response=List[HtmlWidgetSchema],
        permissions=[TokenHasScopePermission(["totem.websitewidget.read"])],
        operation_id="htmlwidgetList",
        summary="List HTML Widget Types",
        tags=["HTML Widget"],
    )
    async def list_widgets(self, request):
        # `async` even though there is nothing to await: ninja picks the whole
        # operation's mode from the view, and `OAuthTokenAuthentication.authenticate`
        # is a coroutine. A sync view sends it through `async_to_sync` and leaves
        # it unawaited -- authentication still works, but it warns. The same
        # applies to `UserController.profile_read`, which is sync.
        #
        # Read straight off the registry: no database to reach.
        return [
            {
                "id": widget.id,
                "title": widget.title,
                "attribute_schema": widget.attribute_schema.model_json_schema(),
            }
            for widget in get_widgets()
        ]
