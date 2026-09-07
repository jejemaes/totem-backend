from django.test import AsyncClient, TransactionTestCase

from website.views import HomePageView, PageView

from .common import WebsiteViewTestMixin


class TestWebsiteAsyncSafety(WebsiteViewTestMixin, TransactionTestCase):
    """Turns the latent hazard into a hard failure.

    In production the render is *not* in the event loop: `render_to_response`
    returns a deferred `TemplateResponse`, and the async handler renders it
    through `sync_to_async(response.render, thread_sensitive=True)` -- a thread
    with no running loop, where django's `async_unsafe` guard never fires. That
    is why the old render-time queries did not crash.

    Here the test body itself is a coroutine, so calling `response.render()`
    *directly* puts the render in a thread that does have a running loop: any
    ORM access then raises `SynchronousOnlyOperation` instead of quietly
    working. `assertNumQueries` says "no query happened"; this says "a query
    could not happen".

    `TransactionTestCase` rather than `TestCase`: async work landing on
    asgiref's shared executor uses another connection and would not see an
    uncommitted test transaction.
    """

    def setUp(self):
        super().setUp()
        self.page = self.build_page(slug="tresor")
        self.menu = self.build_menu_tree(page=self.page)
        self.website = self.build_website(menu=self.menu)
        self.build_widget("FOOTER_1")
        self.build_widget(
            "FOOTER_2", widget_type="last_update_page", param_limit_item=3
        )
        self.build_widget("HOMEPAGE_1")

    async def test_the_homepage_render_is_async_safe(self):
        response = await HomePageView.as_view()(self.build_request("/"))

        response.render()

        self.assertEqual(response.status_code, 200)

    async def test_the_page_render_is_async_safe(self):
        response = await PageView.as_view()(
            self.build_request("/page/tresor/"), slug="tresor"
        )

        response.render()

        self.assertEqual(response.status_code, 200)

    async def test_the_homepage_renders_under_the_async_client(self):
        # Exercises the real ASGI path. It renders inside `sync_to_async`, so it
        # proves reachability rather than async-safety.
        response = await AsyncClient().get("/")

        self.assertEqual(response.status_code, 200)

    async def test_a_page_renders_under_the_async_client(self):
        response = await AsyncClient().get("/page/tresor/")

        self.assertEqual(response.status_code, 200)
