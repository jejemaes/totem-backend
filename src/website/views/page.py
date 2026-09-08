
from core.html_widget import expand_widgets
from website.services import PageService
from website.views.mixins import TemplateResponseMixin, WebsiteRenderContextMixin, View, DetailRecordTemplateWebsiteView


class PageView(DetailRecordTemplateWebsiteView):

    service = PageService
    lookup_field = 'slug'
    lookup_url_kwarg = 'slug'
    template_name = 'website/page.html'
    context_object_name = 'page'

    async def read_records(self, service, filters):
        # "Publicly visible" is the service's definition, not this view's: the
        # last-updated-pages widget must see exactly the same set.
        return await service.read_published(filters=filters)

    async def get_render_context_data(self):
        context = await super().get_render_context_data()
        # Under its own key, never `page.content`: the template must not be able
        # to render the unexpanded field by mistake.
        context['content'] = await expand_widgets(context['page'].content, self.env)
        return self.check_render_context_data(context)


class HomePageView(TemplateResponseMixin, WebsiteRenderContextMixin, View):
    """The root of the site, rendered from the page `Website.homepage` points at.

    One content mechanism instead of two: the homepage body is authored like any
    other page, widget markers included. What stays on `Website` is the site's
    own identity -- its name and headline -- which is not page content.

    `/` must always answer. A system that has just been provisioned has no
    `Website` row, or one with no homepage, and a homepage can be unpublished or
    deleted: every one of those renders the hero alone rather than a 404.
    """

    template_name = 'website/homepage.html'
    template_engine = 'jinja2'

    async def get_website_context_data(self):
        context = await super().get_website_context_data()

        page = await self.get_homepage(context['website'])
        context['page'] = page
        context['content'] = await expand_widgets(
            page.content if page is not None else "", self.env
        )
        return context

    async def get_homepage(self, website):
        if website is None or not website.homepage_id:
            return None

        queryset = await self.env.get(PageService).read_published(
            filters={"id": website.homepage_id}
        )
        # `afirst()` and not `aget()`: the homepage being unpublished or gone is
        # a degradation, not an error on the root of the site.
        return await queryset.afirst()

    async def get(self, request, *args, **kwargs):
        context = await self.get_render_context_data()
        return self.render_to_response(context)
