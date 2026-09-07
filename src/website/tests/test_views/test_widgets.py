from asgiref.sync import async_to_sync
from django.test import TestCase

from core.services import Environment
from website.models import Page, Widget
from website.services import WidgetService
from website.website_widget import RendererWidgetRegistry

from .common import WebsiteViewTestMixin


class TestWidgetRendering(WebsiteViewTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(WidgetService)

    def _registry(self, prefix="FOOTER_"):
        return async_to_sync(self.service.read_render_registry)(prefix)

    def test_a_custom_html_widget_renders_its_content(self):
        self.build_widget("FOOTER_1")

        self.assertIn("Bloc", self._registry()["FOOTER_1"])

    def test_a_missing_position_renders_empty(self):
        self.assertEqual(self._registry()["FOOTER_3"], "")

    def test_a_last_update_page_widget_lists_published_pages_only(self):
        self.build_page(slug="published", published=True)
        self.build_page(slug="draft", published=False)
        self.build_widget(
            "FOOTER_1", widget_type="last_update_page", param_limit_item=5
        )

        rendered = self._registry()["FOOTER_1"]

        self.assertIn("/page/published/", rendered)
        self.assertNotIn("/page/draft/", rendered)

    def test_a_last_update_page_widget_respects_its_limit(self):
        for index in range(3):
            self.build_page(slug=f"page-{index}")
        self.build_widget(
            "FOOTER_1", widget_type="last_update_page", param_limit_item=2
        )

        rendered = self._registry()["FOOTER_1"]

        self.assertEqual(rendered.count("/page/page-"), 2)

    def test_a_last_update_page_widget_orders_by_the_update_date(self):
        older = self.build_page(slug="older")
        newer = self.build_page(slug="newer")
        # `update_date` is `auto_now`, so touch the rows to control the order.
        Page.objects.filter(pk=older.pk).update(title="Older")
        Page.objects.filter(pk=newer.pk).update(title="Newer")
        self.build_widget(
            "FOOTER_1", widget_type="last_update_page", param_limit_item=5
        )

        rendered = self._registry()["FOOTER_1"]

        self.assertLess(
            rendered.index("/page/newer/"), rendered.index("/page/older/")
        )

    def test_rendering_makes_no_query(self):
        # Everything the widget needs is read by `read_render_registry`, in the
        # async phase and through the services. `__getitem__` runs while the
        # template renders, where a query would escape both.
        self.build_page(slug="published")
        self.build_widget("FOOTER_1")
        self.build_widget(
            "FOOTER_2", widget_type="last_update_page", param_limit_item=3
        )
        registry = self._registry()

        with self.assertNumQueries(0):
            registry["FOOTER_1"]
            registry["FOOTER_2"]

    def test_an_unknown_widget_type_renders_empty(self):
        # A stale `widget_type` in the database is an empty slot, not a 500
        # halfway through the page.
        self.build_widget("FOOTER_1")
        Widget.objects.filter(position="FOOTER_1").update(widget_type="gone")

        self.assertEqual(self._registry()["FOOTER_1"], "")

    def test_the_registry_refuses_a_lazy_queryset(self):
        # It used to take the queryset and iterate it lazily from the template.
        with self.assertRaises(TypeError) as ctx:
            RendererWidgetRegistry(Widget.objects.all())

        self.assertIn("materialized", str(ctx.exception))

    def test_the_registry_refuses_a_manager(self):
        with self.assertRaises(TypeError):
            RendererWidgetRegistry(Widget.objects)
