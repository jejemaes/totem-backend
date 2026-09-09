from asgiref.sync import async_to_sync
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from core.html_widget import expand_widgets, get_widget
from core.services import Environment
from website.models import Menu, Page


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


class TestSideMenuWidget(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.page = Page.objects.create(
            title="Camp", slug="camp", content="<p>x</p>", is_published=True
        )
        cls.main = Menu.objects.create(name="Main")
        # The realistic shape: a side menu points at a section of the main menu,
        # not at a top-level item.
        # A child menu needs a target: `menu_page_or_link` says so.
        cls.section = Menu.objects.create(
            name="Activities", parent=cls.main, link="/activities/"
        )
        cls.second = Menu.objects.create(
            name="Second", parent=cls.section, link="/b/", sequence=20
        )
        cls.first = Menu.objects.create(
            name="First", parent=cls.section, page=cls.page, sequence=10
        )
        cls.nested = Menu.objects.create(
            name="Nested", parent=cls.first, link="/c/"
        )

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.widget = get_widget("side-menu")

    def expand(self, attrs):
        return async_to_sync(expand_widgets)(
            f'''<div><t-widget name="side-menu" attrs='{attrs}'></t-widget></div>''',
            self.env,
        )

    def test_it_lists_the_descendants_of_the_root(self):
        rendered = self.expand(f'{{"menu_id": "{self.section.pk}"}}')

        # `first` targets a page, `second` a raw link: both resolve to a href.
        self.assertIn('href="/page/camp/"', rendered)
        self.assertIn('href="/b/"', rendered)
        self.assertIn('href="/c/"', rendered)
        # `sequence` order, and the root heads the block rather than linking
        # to its own target.
        self.assertLess(rendered.index("First"), rendered.index("Second"))
        self.assertNotIn('href="/activities/"', rendered)

    def test_it_nests_the_deeper_levels(self):
        rendered = self.expand(f'{{"menu_id": "{self.section.pk}"}}')

        # The grandchild lives inside its parent item, not next to it.
        self.assertLess(rendered.index("First"), rendered.index("Nested"))
        self.assertLess(rendered.index("Nested"), rendered.index("Second"))
        self.assertEqual(rendered.count("<ul>"), 2)

    def test_the_root_names_the_heading(self):
        self.assertIn("<h5>Activities</h5>", self.expand(
            f'{{"menu_id": "{self.section.pk}"}}'
        ))

    def test_the_heading_can_be_overridden(self):
        rendered = self.expand(
            f'{{"menu_id": "{self.section.pk}", "heading": "In this section"}}'
        )

        self.assertIn("<h5>In this section</h5>", rendered)
        self.assertNotIn("Activities", rendered)

    def test_the_css_class_lands_on_every_item(self):
        rendered = self.expand(
            f'{{"menu_id": "{self.section.pk}", "css_class": "nav-item"}}'
        )

        # Three items, the nested one included.
        self.assertEqual(rendered.count('class="nav-item"'), 3)

    def test_the_css_class_is_optional(self):
        self.assertNotIn("class=", self.expand(f'{{"menu_id": "{self.section.pk}"}}'))

    def test_a_new_window_item_targets_a_blank_one(self):
        Menu.objects.create(
            name="Elsewhere", parent=self.section, link="/d/", new_window=True
        )

        rendered = self.expand(f'{{"menu_id": "{self.section.pk}"}}')

        self.assertIn('href="/d/" target="_blank"', rendered)
        self.assertNotIn('href="/b/" target="_blank"', rendered)

    def test_a_leaf_root_renders_its_heading_alone(self):
        rendered = self.expand(f'{{"menu_id": "{self.nested.pk}"}}')

        self.assertIn("<h5>Nested</h5>", rendered)
        self.assertNotIn("<ul>", rendered)

    def test_an_unknown_menu_renders_the_heading_alone(self):
        # A widget is content: an id pointing at a deleted menu must not empty
        # the block it sits in, let alone raise.
        for menu_id in ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "not-a-ulid"):
            rendered = self.expand(
                f'{{"menu_id": "{menu_id}", "heading": "Section"}}'
            )

            self.assertIn("<h5>Section</h5>", rendered)
            self.assertNotIn("<ul>", rendered)

    def test_the_menu_id_is_required(self):
        with self.assertRaises(PydanticValidationError):
            self.widget.validate_attributes({})

    def test_an_unknown_parameter_is_refused(self):
        with self.assertRaises(PydanticValidationError):
            self.widget.validate_attributes({"menu_id": "x", "cssclass": "a"})

    def test_a_css_class_is_bounded_by_its_schema(self):
        for value in ('a" onclick="x', "<script>", "a" * 129):
            with self.assertRaises(PydanticValidationError):
                self.widget.validate_attributes({"menu_id": "x", "css_class": value})

    def test_it_exposes_a_json_schema_for_the_editor(self):
        schema = self.widget.attribute_schema.model_json_schema()

        self.assertEqual(schema["required"], ["menu_id"])
        self.assertEqual(
            set(schema["properties"]), {"menu_id", "heading", "css_class"}
        )
