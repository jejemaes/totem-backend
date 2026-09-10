from typing import List

from core.api import BaseController, route
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermission
from website.schemas import LayoutSchema, ThemeSchema
from website.theme import get_layouts, get_themes


class ThemeController(BaseController):
    """The themes a site can be rendered with, and the layouts a page can pick.

    Deliberately not a `ModelController`, and the second controller in the
    project with neither a model nor a service -- `HtmlWidgetController` being
    the first, for the same reason. A theme has no database row: the registry in
    `website.theme` is the source of truth, filled at startup by
    `autodiscover_modules('theme')` in `WebsiteConfig.ready()`, and only the
    selection is stored (`Website.theme`, `Page.layout`).
    `validate_controllers` skips a controller whose `model` is None, so nothing
    at startup expects otherwise.

    Permissions go on the routes rather than through
    `TokenHasScopePermissionModelControllerMixin`: that mixin maps CRUD
    operations to scopes via `permission_map`, and there is no CRUD operation
    here to map.
    """

    api = api_v1
    path_prefix = "/website/themes/"
    auth = [OAuthTokenAuthentication()]

    @route.get(
        "/",
        response=List[ThemeSchema],
        permissions=[TokenHasScopePermission(["totem.websitetheme.read"])],
        operation_id="themeList",
        summary="List Website Themes",
        tags=["Theme"],
    )
    async def list_themes(self, request):
        # `async` even though there is nothing to await: ninja picks the whole
        # operation's mode from the view, and `OAuthTokenAuthentication.authenticate`
        # is a coroutine. A sync view sends it through `async_to_sync` and leaves
        # it unawaited -- authentication still works, but it warns. Same as
        # `HtmlWidgetController.list_widgets`.
        #
        # Read straight off the registry: no database to reach.
        return [
            {
                "id": theme.id,
                "title": theme.title,
                "layouts": sorted(theme.layouts),
                "option_schema": theme.option_schema.model_json_schema(),
            }
            for theme in get_themes()
        ]

    @route.get(
        "/layouts/",
        response=List[LayoutSchema],
        permissions=[TokenHasScopePermission(["totem.websitetheme.read"])],
        operation_id="themeLayoutList",
        summary="List Page Layouts",
        tags=["Theme"],
    )
    async def list_layouts(self, request):
        # The vocabulary with its human labels, which belongs to the vocabulary
        # and not to any one theme -- `ThemeSchema.layouts` only says which of
        # them a theme implements. Without this route an editor would restate the
        # labels in javascript, the exact duplication `option_schema` exists to
        # avoid.
        #
        # Registered after `/` and before nothing: there is no `/{id}/` route
        # here, so the `cls.__dict__` ordering that matters for
        # `WebsiteController.current_read` is not load-bearing in this class.
        return [
            {"id": layout_id, "title": title} for layout_id, title in get_layouts()
        ]
