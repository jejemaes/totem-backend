
from django.core.exceptions import ValidationError
from django.db.models import Manager, QuerySet
from django.http import Http404
from django.views.generic.base import TemplateResponseMixin, View

from core.html_widget import expand_widgets
from core.views.mixins import EnvironmentViewMixin
from website.models import Website
from website.services import MenuService

#-----------------------------------------
# Simple Rendering Helpers
#-----------------------------------------

class RenderContextMixin:
    """
    A default context mixin that passes the keyword arguments received by
    get_render_context_data() as the template context.
    """

    extra_context = None

    async def get_render_context_data(self):
        context = {}
        context.setdefault("view", self)
        if self.extra_context is not None:
            context.update(self.extra_context)
        return context

    def check_render_context_data(self, context):
        """Refuse a lazy value in the render context.

        The template renders outside any `sync_to_async` hop, so a queryset
        handed to it queries the database mid-render -- past the service layer
        and past its access rules. Cheap guard against the whole class of bug.
        """
        for key, value in context.items():
            if isinstance(value, (QuerySet, Manager)):
                raise TypeError(
                    f"context[{key!r}] is a lazy {type(value).__name__}: the "
                    "template renders outside of any `sync_to_async` hop, so it "
                    "would query the database mid-render. Materialize it in the "
                    "view."
                )
        return context

#-----------------------------------------
# Website Layout
#-----------------------------------------

class WebsiteRenderContextMixin(EnvironmentViewMixin, RenderContextMixin):

    async def get_render_context_data(self):
        context = await super().get_render_context_data()
        context.update(await self.get_website_context_data())
        return self.check_render_context_data(context)

    async def get_website_context_data(self):
        # TODO : to be cached ?
        website = await self.get_website()

        menu_root = None
        if website is not None and website.menu_id:
            menu_root = await self.env.get(MenuService).read_tree(website.menu_id)

        return {
            'website': website,
            # A list, never None: the template used to walk `menu_tree.children`,
            # which raises `UndefinedError` in jinja as soon as the website has
            # no main menu -- the branch the code already took when `menu_id`
            # was unset.
            'menu_nodes': menu_root.children if menu_root is not None else [],
            # The footer used to be four fixed widget slots. It is now one
            # `HtmlField` the author lays out, widget markers included -- one
            # content mechanism instead of two.
            'footer': await expand_widgets(
                website.footer if website is not None else "", self.env
            ),
        }

    async def get_website(self):
        """The website record, or None.

        `Website` has no service on purpose: a singleton read with no access
        rule of its own. Isolated in one overridable method so that swapping in
        a `WebsiteService` later is a one-line change, and so that grepping for
        "ORM left in the website views" returns exactly this.

        `afirst()` is already an async hop, and `first()` orders by pk on an
        unordered queryset, so the read is deterministic even though nothing
        constrains the table to a single row. Returns None on a database that
        has not been populated yet -- callers must handle it.
        """
        return await Website.objects.afirst()


class DetailRecordTemplateWebsiteView(TemplateResponseMixin, WebsiteRenderContextMixin, View):
    """ Helper class based view to render a single object """

    # The service the record is read through, in place of a raw queryset: the
    # filter then stays inside the service (and inside its access rules)
    # instead of narrowing it from outside.
    service = None

    # If you want to use object lookups other than pk, set 'lookup_field'.
    # For more complex lookup requirements override `get_object()`.
    lookup_field = 'pk'
    lookup_url_kwarg = None
    # Variable name the object will have in render context
    context_object_name = 'object'

    # Template
    template_name = None
    template_engine = 'jinja2'

    def get_service(self):
        assert self.service is not None, (
            "'%s' should either include a `service` attribute, "
            "or override the `get_service()` method."
            % self.__class__.__name__
        )
        return self.env.get(self.service)

    def get_lookup_filters(self):
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        return {self.lookup_field: self.kwargs[lookup_url_kwarg]}

    async def read_records(self, service, filters):
        """The (still unevaluated) queryset the lookup runs on.

        The single hook a subclass overrides to pick a narrower read of its
        service -- publication, archiving, language...
        """
        return await service.read(filters=filters)

    async def get_object(self):
        """
        Returns the object the view is displaying.

        You may want to override this if you need to provide non-standard
        queryset lookups.  Eg if objects are referenced using multiple
        keyword arguments in the url conf.
        """
        service = self.get_service()
        try:
            queryset = await self.read_records(service, self.get_lookup_filters())
            # `aget()` materializes in one `sync_to_async` hop: every concrete
            # field loaded, every declared prefetch resolved. Same call as
            # `RetrieveModelControllerMixin.retrieve`.
            return await queryset.aget()
        except service.model.DoesNotExist as exc:
            raise Http404(
                f"No {service.model._meta.verbose_name} matches the given query."
            ) from exc
        except (TypeError, ValueError, ValidationError) as exc:
            # An ill-typed lookup value is a 404, not a 500.
            raise Http404 from exc

    async def get_render_context_data(self):
        """Insert the single object into the context dict."""
        record = await self.get_object()  # might raise NotFound: Rather do it before fetching website context
        context = await super().get_render_context_data()
        if record:
            context["object"] = record
            if self.context_object_name:
                context[self.context_object_name] = record
        return self.check_render_context_data(context)

    async def get(self, request, *args, **kwargs):
        context = await self.get_render_context_data()
        return self.render_to_response(context)
