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
