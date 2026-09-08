from asgiref.sync import async_to_sync
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from core.html_widget import expand_widgets, get_widget
from core.services import Environment
from website.models import Page


class TestLastUpdatePageWidget(TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.widget = get_widget("last-page")

    def expand(self, attrs=None):
        rendered = f" attrs='{attrs}'" if attrs else ""
        return async_to_sync(expand_widgets)(
            f'<div><t-widget name="last-page"{rendered}></t-widget></div>', self.env
        )

    def test_it_lists_published_pages_only(self):
        Page.objects.create(
            title="Published", slug="published", content="<p>x</p>", is_published=True
        )
        Page.objects.create(title="Draft", slug="draft", content="<p>x</p>")

        rendered = self.expand()

        self.assertIn("/page/published/", rendered)
        self.assertNotIn("/page/draft/", rendered)

    def test_it_respects_its_limit(self):
        for index in range(4):
            Page.objects.create(
                title=f"Page {index}", slug=f"page-{index}",
                content="<p>x</p>", is_published=True,
            )

        self.assertEqual(self.expand('{"limit": 2}').count("/page/page-"), 2)

    def test_it_orders_by_the_update_date(self):
        older = Page.objects.create(
            title="Older", slug="older", content="<p>x</p>", is_published=True
        )
        newer = Page.objects.create(
            title="Newer", slug="newer", content="<p>x</p>", is_published=True
        )
        # `update_date` is `auto_now`, so touch the rows to control the order.
        Page.objects.filter(pk=older.pk).update(title="Older")
        Page.objects.filter(pk=newer.pk).update(title="Newer")

        rendered = self.expand()

        self.assertLess(
            rendered.index("/page/newer/"), rendered.index("/page/older/")
        )

    def test_the_heading_is_optional(self):
        Page.objects.create(
            title="P", slug="p", content="<p>x</p>", is_published=True
        )

        self.assertNotIn("<h5>", self.expand())
        self.assertIn("Latest", self.expand('{"heading": "Latest"}'))

    def test_the_limit_is_bounded_by_its_schema(self):
        for value in (0, 99):
            with self.assertRaises(PydanticValidationError):
                self.widget.validate_attributes({"limit": value})

    def test_an_unknown_parameter_is_refused(self):
        # `extra="forbid"`, so a typo is reported rather than silently ignored.
        with self.assertRaises(PydanticValidationError):
            self.widget.validate_attributes({"limitt": 5})

    def test_it_exposes_a_json_schema_for_the_editor(self):
        schema = self.widget.attribute_schema.model_json_schema()

        self.assertEqual(schema["properties"]["limit"]["maximum"], 10)
        self.assertEqual(schema["properties"]["limit"]["minimum"], 1)
