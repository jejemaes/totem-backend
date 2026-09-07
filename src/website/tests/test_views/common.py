from asgiref.sync import async_to_sync
from django.test import RequestFactory

from website.models import Menu, Page, Website, Widget


class WebsiteViewTestMixin:
    """Helpers for the server-rendered website views.

    `core.testing.APITestCaseMixin` is bearer-token and JSON-body plumbing, none
    of which applies here. What an SSR test needs instead is a way to get at the
    response *before* it is rendered, so that "which queries happen at render
    time" can be asserted at all.
    """

    def build_website(self, menu=None):
        return Website.objects.create(
            name="Moulinsart", headline="<p>Le domaine</p>", menu=menu
        )

    def build_menu_tree(self, page=None):
        root = Menu.objects.create(name="Main")
        Menu.objects.create(name="Home", parent=root, link="/", sequence=10)
        if page is not None:
            Menu.objects.create(name="Page", parent=root, page=page, sequence=20)
        return root

    def build_page(self, slug="tresor", published=True):
        return Page.objects.create(
            title="Le Trésor de Rackham",
            slug=slug,
            content="<p>Mille sabords</p>",
            is_published=published,
        )

    def build_widget(self, position, widget_type="custom_html", **kwargs):
        values = {"param_content": "<p>Bloc</p>"} if widget_type == "custom_html" else {}
        values.update(kwargs)
        return Widget.objects.create(
            title=f"Widget {position}",
            widget_type=widget_type,
            position=position,
            **values,
        )

    def build_request(self, path):
        return RequestFactory().get(path)

    def get_unrendered_response(self, view_class, path, **kwargs):
        """The `TemplateResponse` for `view_class`, not yet rendered.

        The view is async, and `async_to_sync` runs it in an event loop on
        another thread while this one blocks; its own
        `sync_to_async(thread_sensitive=True)` hops then come back *here*, so
        the connection and the test transaction are shared and
        `assertNumQueries` sees everything (see the module docstring of
        `core.services.mixins`).
        """
        return async_to_sync(view_class.as_view())(
            self.build_request(path), **kwargs
        )
