import logging

from django.core.exceptions import ValidationError
from django.db.models import Manager, QuerySet
from django.http import Http404
from django.views.generic.base import TemplateResponseMixin, View

from core.html_widget import expand_widgets
from core.views.mixins import EnvironmentViewMixin
from website.services import MenuService, WebsiteService
from website.theme import DEFAULT_THEME_ID, LAYOUT_DEFAULT, get_theme

_logger = logging.getLogger(__name__)

# -----------------------------------------
# Simple Rendering Helpers
# -----------------------------------------

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

# -----------------------------------------
# Website Layout
# -----------------------------------------

class WebsiteRenderContextMixin(EnvironmentViewMixin, RenderContextMixin):

    async def get_render_context_data(self):
        context = await super().get_render_context_data()
        context.update(await self.get_website_context_data())
        # After `get_website_context_data`, not inside it: `HomePageView`
        # resolves the page it renders in there, and `get_layout()` reads it.
        context['layout'] = self.get_layout()
        return self.check_render_context_data(context)

    # The theme used when there is no `Website` row at all, and when the row
    # names one that is no longer registered. Never None: `/` must answer.
    default_theme_id = DEFAULT_THEME_ID

    async def get_website_context_data(self):
        # TODO : to be cached ?
        website = await self.get_website()

        # Stashed as well as returned: `get_template_names()` runs later, in the
        # sync render phase, and must name a template of *the same* theme the
        # context describes -- recomputing it there would need the `Website` row
        # it does not have.
        theme = self.theme = self.get_theme(website)

        menu_root = None
        if website is not None and website.menu_id:
            menu_root = await self.env.get(MenuService).read_tree(website.menu_id)

        return {
            "website": website,
            # A list, never None: the template used to walk `menu_tree.children`,
            # which raises `UndefinedError` in jinja as soon as the website has
            # no main menu -- the branch the code already took when `menu_id`
            # was unset.
            "menu_nodes": menu_root.children if menu_root is not None else [],
            # The footer used to be four fixed widget slots. It is now one
            # `HtmlField` the author lays out, widget markers included -- one
            # content mechanism instead of two.
            "footer": await expand_widgets(
                website.footer if website is not None else "", self.env
            ),
            "side_bar_content": await expand_widgets(
                website.side_bar_content if website is not None else "", self.env
            ),
            # The theme object itself, not just its id: a layout reads
            # `theme.stylesheets` and `theme.base_template` off it. A plain
            # python object holding no lazy attribute, so
            # `check_render_context_data` has nothing to object to.
            "theme": theme,
            # Rendered in python, never by a template filter: escaping cannot
            # make a value safe inside a `<style>`, which is why
            # `render_css_variables` validates instead.
            "theme_style": theme.render_css_variables(
                theme.resolve_options(
                    website.theme_options if website is not None else None
                )
            ),
        }

    def get_theme(self, website):
        """The theme for this render. Never None.

        Sync and I/O-free on purpose: it reads the already-loaded `Website` row
        and the in-process registry, so resolving a theme costs no query at all
        -- an `assertNumQueries` pins that.

        A stored id that no longer resolves -- a theme deleted from the code
        while a row still points at it -- degrades to the default and logs, the
        same contract `expand_widgets` gives a broken widget marker.
        """
        theme_id = (website.theme if website is not None else None) or self.default_theme_id
        theme = get_theme(theme_id)
        if theme is None:
            _logger.warning(
                "Unknown theme %r on the website, falling back to %r.",
                theme_id,
                self.default_theme_id,
            )
            # `raise_if_not_found` on this last rung: a missing *default* theme
            # is a broken build, not a data problem, and must not be swallowed
            # into a blank page.
            theme = get_theme(self.default_theme_id, raise_if_not_found=True)
        return theme

    async def get_website(self):
        """The website record, or None.

        Read through `WebsiteService` like every other record, so the last of the
        ORM this module used to hold is gone. Returns None on a database that
        has not been populated yet -- callers must handle it.

        No `fields=`, deliberately: it would become an `only()`, and the layout
        reads `name`/`headline` while `get_website_context_data` reads
        `menu_id`, `homepage_id` and `footer`. A name missing from that list
        raises `SynchronousOnlyOperation` during the template render, well past
        any hop this view controls -- see `read_current`.

        Costs no more than the previous `Website.objects.afirst()`:
        `apply_access_rules` returns the queryset untouched for a model with no
        rule registered, and `Environment.get_access_roles()` issues no query
        when `user is None`, which is every request on the public site.
        """
        return await self.env.get(WebsiteService).read_current()


class ThemeTemplateResponseMixin(TemplateResponseMixin):
    """`TemplateResponseMixin` whose template comes from the theme, not the view.

    Subclasses `TemplateResponseMixin` rather than sitting beside it: as a
    sibling it would lose the MRO to it in `DetailRecordTemplateWebsiteView`,
    whose bases put `TemplateResponseMixin` first, and the override would
    silently never run.

    Two ways to name a template, and a view picks one. Leave `template_name`
    unset and the theme's layouts answer, which is what a `Page` wants. Set it
    to a template the app ships -- `"event/event_detail.html"` -- and the theme
    gets a chance to override it before the app's own file answers; that
    template extends `theme.base_template` and so inherits this site's chrome
    without knowing a theme id. That second form is what keeps a new content
    type at one file and costs existing themes nothing.
    """

    template_engine = 'jinja2'

    # The app's own template, for the second form above. None means "resolve a
    # layout".
    template_name = None

    # Set by `WebsiteRenderContextMixin.get_website_context_data`.
    theme = None

    layout = LAYOUT_DEFAULT

    def get_layout(self):
        return self.layout

    def get_template_names(self):
        # `render_to_response` runs after `get_render_context_data()` has been
        # awaited, so the theme is resolved by now. Asserted rather than
        # resolved here: resolving needs the `Website` row, and reading it from
        # this sync method is exactly the synchronous ORM call in an async view
        # that this module is organised to prevent.
        assert self.theme is not None, (
            f"{type(self).__name__}.get_template_names() ran before the theme "
            "was resolved: `get_render_context_data()` must be awaited first."
        )
        if self.template_name:
            return self.theme.get_template_names(self.template_name)
        return self.theme.get_layout_template_names(self.get_layout())


class DetailRecordTemplateWebsiteView(ThemeTemplateResponseMixin, WebsiteRenderContextMixin, View):
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
        # On the view before the context is built: `get_layout()` reads it, and
        # it runs as part of that build.
        self.object = record
        context = await super().get_render_context_data()
        if record:
            context["object"] = record
            if self.context_object_name:
                context[self.context_object_name] = record
        return self.check_render_context_data(context)

    async def get(self, request, *args, **kwargs):
        context = await self.get_render_context_data()
        return self.render_to_response(context)
