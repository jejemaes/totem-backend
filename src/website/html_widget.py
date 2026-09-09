from pydantic import BaseModel, ConfigDict, Field

from core.html_widget import AbstractHtmlWidget


class LastUpdatePageWidget(AbstractHtmlWidget):
    id = "last-page"
    title = "Last Updated Pages"
    template_name = "website/widgets/last_update_page.html"

    class Attributes(BaseModel):
        # `extra="forbid"` so a typo in the marker is reported instead of
        # silently ignored.
        model_config = ConfigDict(extra="forbid")

        heading: str = Field(
            "", max_length=256, description="Optional heading above the list."
        )
        limit: int = Field(
            5, ge=1, le=10, description="How many pages to list, at most."
        )

    attribute_schema = Attributes

    async def get_render_context(self, attributes, env):
        # Local import: `website.services` reaches the models, which reach this
        # module through the widget autodiscovery.
        from website.services import PageService

        queryset = await env.get(PageService).read_published(
            ordering=["-update_date"]
        )
        return {
            "heading": attributes.heading,
            "pages": [page async for page in queryset[0 : attributes.limit]],
        }


class SideMenuWidget(AbstractHtmlWidget):
    id = "side-menu"
    title = "Side Menu"
    template_name = "website/widgets/side_menu.html"

    class Attributes(BaseModel):
        # `extra="forbid"` so a typo in the marker is reported instead of
        # silently ignored.
        model_config = ConfigDict(extra="forbid")

        menu_id: str = Field(
            ...,
            max_length=32,
            description="Identifier of the root menu item, whose descendants are listed.",
        )
        heading: str = Field(
            "",
            max_length=256,
            description="Optional heading, overriding the root menu item's name.",
        )
        # The pattern is hygiene rather than escaping -- jinja escapes the
        # attribute value anyway. It turns a junk class into a validation error
        # when the content is saved, instead of junk markup on the page.
        css_class: str = Field(
            "",
            max_length=128,
            pattern=r"^[A-Za-z0-9_\- ]*$",
            description="Optional CSS classes added to every item of the list.",
        )

    attribute_schema = Attributes

    async def get_render_context(self, attributes, env):
        # Local import: `website.services` reaches the models, which reach this
        # module through the widget autodiscovery.
        from website.services import MenuService

        # `read_tree` resolves the target page of every item, which is what lets
        # the template evaluate `node.data.url` -- a `page.slug` dereference,
        # synchronous and out of reach of any `sync_to_async` hop.
        root = await env.get(MenuService).read_tree(attributes.menu_id)
        return {
            # An explicit heading wins; otherwise the root item names the block.
            # A menu that does not exist -- or that the visitor may not read --
            # leaves the heading the author wrote, and nothing else.
            "heading": attributes.heading or (root.data.name if root else ""),
            "nodes": root.children if root else [],
            "css_class": attributes.css_class,
        }
