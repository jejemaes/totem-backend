
from website.choices import WIDGET_POSITION_HOMEPAGE_PREFIX
from website.services import PageService, WidgetService
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


class HomePageView(TemplateResponseMixin, WebsiteRenderContextMixin, View):

    template_name = 'website/homepage.html'
    template_engine = 'jinja2'

    async def get_website_context_data(self):
        context = await super().get_website_context_data()
        context['homepage_widgets'] = await self.env.get(
            WidgetService
        ).read_render_registry(WIDGET_POSITION_HOMEPAGE_PREFIX)
        return context

    async def get(self, request, *args, **kwargs):
        context = await self.get_render_context_data()
        return self.render_to_response(context)
