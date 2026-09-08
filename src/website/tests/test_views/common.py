from asgiref.sync import async_to_sync
from django.test import RequestFactory

from website.models import Menu, Page, Website


class WebsiteViewTestMixin:
    """Helpers for the server-rendered website views.

    `core.testing.APITestCaseMixin` is bearer-token and JSON-body plumbing, none
    of which applies here. What an SSR test needs instead is a way to get at the
    response *before* it is rendered, so that "which queries happen at render
    time" can be asserted at all.
    """

    def build_website(self, menu=None, homepage=None, footer=None):
        return Website.objects.create(
            name="Moulinsart",
            headline="<p>Le domaine</p>",
            menu=menu,
            homepage=homepage,
            footer=footer,
        )

    def build_menu_tree(self, page=None):
        root = Menu.objects.create(name="Main")
        Menu.objects.create(name="Home", parent=root, link="/", sequence=10)
        if page is not None:
            Menu.objects.create(name="Page", parent=root, page=page, sequence=20)
        return root

    def build_page(self, slug="tresor", published=True, content=None):
        return Page.objects.create(
            title="Le Trésor de Rackham",
            slug=slug,
            content=content or "<p>Mille sabords</p>",
            is_published=published,
        )

    def marker(self, name="last-page", attrs=None):
        """A widget marker, as an author would write it in the content."""
        import json

        rendered_attrs = f" attrs='{json.dumps(attrs)}'" if attrs else ""
        return f'<t-widget name="{name}"{rendered_attrs}></t-widget>'

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
