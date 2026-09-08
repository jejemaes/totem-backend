from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase
from django.utils.safestring import SafeString, mark_safe
from parameterized import parameterized
from pydantic import BaseModel, ConfigDict, Field

from core.html_widget import (
    AbstractHtmlWidget,
    expand_widgets,
    get_widget,
    get_widgets,
)
from core.services import Environment

# Widgets registered for the whole process, like the test access rules in
# `user`. Their ids are prefixed so nothing in the project can reference them,
# and they override `render` directly rather than going through a template --
# `render` is the single entry point `expand_widgets` uses.


class EchoWidget(AbstractHtmlWidget):
    id = "test-echo"
    title = "Echo"

    class Attributes(BaseModel):
        model_config = ConfigDict(extra="forbid")

        text: str = Field("W", max_length=10)

    attribute_schema = Attributes

    async def render(self, attributes, env):
        return mark_safe(f"<b>{attributes.text}</b>")


class BlocksWidget(AbstractHtmlWidget):
    """Renders several top-level elements, which the splice has to handle."""

    id = "test-blocks"
    title = "Blocks"

    async def render(self, attributes, env):
        return mark_safe("<p>1</p><p>2</p>")


class TextWidget(AbstractHtmlWidget):
    """Renders bare text: there is no element for the splice to hang it on."""

    id = "test-text"
    title = "Text"

    async def render(self, attributes, env):
        return mark_safe("plain")


class EmptyWidget(AbstractHtmlWidget):
    id = "test-empty"
    title = "Empty"

    async def render(self, attributes, env):
        return mark_safe("")


class BoomWidget(AbstractHtmlWidget):
    id = "test-boom"
    title = "Boom"

    async def render(self, attributes, env):
        raise RuntimeError("this widget is broken")


class RecursiveWidget(AbstractHtmlWidget):
    """Renders a marker of its own, which must not be expanded in turn."""

    id = "test-recursive"
    title = "Recursive"

    async def render(self, attributes, env):
        return mark_safe('<t-widget name="test-echo"></t-widget>')


def marker(name="test-echo", attrs=None):
    rendered = f" attrs='{attrs}'" if attrs else ""
    return f'<t-widget name="{name}"{rendered}></t-widget>'


class TestWidgetRegistry(SimpleTestCase):

    def test_a_widget_is_registered_under_its_id(self):
        self.assertIsInstance(get_widget("test-echo"), EchoWidget)

    def test_an_unknown_id_resolves_to_none(self):
        self.assertIsNone(get_widget("no-such-widget"))

    def test_an_unknown_id_can_raise_on_demand(self):
        with self.assertRaises(ValueError):
            get_widget("no-such-widget", raise_if_not_found=True)

    def test_the_abstract_base_is_not_a_widget(self):
        # It has no id, so nothing can reference it and it must not sit in the
        # registry offering itself as a choice.
        self.assertNotIn(None, [widget.id for widget in get_widgets()])

    def test_the_listing_is_ordered_by_id(self):
        ids = [widget.id for widget in get_widgets()]

        self.assertEqual(ids, sorted(ids))

    def test_two_widgets_can_not_share_an_id(self):
        with self.assertRaises(ValueError):

            class Duplicate(AbstractHtmlWidget):  # noqa: F811
                id = "test-echo"
                title = "Duplicate"

    def test_a_registered_widget_must_declare_a_title(self):
        # It is what the editor shows in its list of blocks, so a blank one is
        # useless there.
        with self.assertRaises(ValueError):

            class Untitled(AbstractHtmlWidget):
                id = "test-untitled"


class TestExpandWidgets(TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(None)

    def expand(self, content):
        return async_to_sync(expand_widgets)(content, self.env)

    # ------------------------------------------
    # Tests Short Circuit
    # ------------------------------------------

    @parameterized.expand([("empty", ""), ("none", None)])
    def test_an_absent_content_expands_to_nothing(self, dummy, content):
        self.assertEqual(self.expand(content), "")

    def test_content_without_a_marker_is_returned_untouched(self):
        # And not reparsed: the overwhelmingly common case should cost nothing
        # but a substring search.
        content = "<div><p>a</p><p>b</p></div>"

        with self.assertNumQueries(0):
            self.assertEqual(self.expand(content), content)

    def test_the_result_is_safe_so_a_template_does_not_escape_it(self):
        self.assertIsInstance(self.expand(f"<div>{marker()}</div>"), SafeString)

    # ------------------------------------------
    # Tests Splicing
    # ------------------------------------------

    @parameterized.expand(
        [
            ("alone", "<div>{m}</div>", "<div><b>W</b></div>"),
            ("surrounded by text", "<div>before {m} after</div>", "<div>before <b>W</b> after</div>"),
            ("first", "<div>{m}after</div>", "<div><b>W</b>after</div>"),
            ("last", "<div>before{m}</div>", "<div>before<b>W</b></div>"),
            ("inside a paragraph", "<div><p>a {m} b</p></div>", "<div><p>a <b>W</b> b</p></div>"),
            ("twice", "<div>a{m}b{m}c</div>", "<div>a<b>W</b>b<b>W</b>c</div>"),
        ]
    )
    def test_the_text_around_a_marker_survives(self, dummy, template, expected):
        # lxml keeps the text after an element on that element, so a naive
        # replace loses or duplicates it.
        self.assertEqual(self.expand(template.format(m=marker())), expected)

    @parameterized.expand(
        [
            ("several blocks", "test-blocks", "<div>x<p>1</p><p>2</p>y</div>"),
            ("bare text", "test-text", "<div>xplainy</div>"),
            ("nothing at all", "test-empty", "<div>xy</div>"),
        ]
    )
    def test_whatever_shape_the_widget_renders(self, dummy, name, expected):
        content = f"<div>x{marker(name=name)}y</div>"

        self.assertEqual(self.expand(content), expected)

    def test_the_parameters_reach_the_widget(self):
        content = f"""<div>{marker(attrs='{"text": "hi"}')}</div>"""

        self.assertEqual(self.expand(content), "<div><b>hi</b></div>")

    # ------------------------------------------
    # Tests Failure Isolation
    # ------------------------------------------

    @parameterized.expand(
        [
            ("unknown widget", marker(name="no-such-widget")),
            ("parameters fail the schema", marker(attrs='{"text": "far too long to pass"}')),
            ("parameters are not json", '<t-widget name="test-echo" attrs="nope"></t-widget>'),
            ("the widget raises", marker(name="test-boom")),
        ]
    )
    def test_a_broken_widget_becomes_an_empty_slot(self, dummy, bad_marker):
        # Content must never be able to take a page down. Validation refuses
        # most of this on save, but it is write-time only: a fixture, a data
        # migration or a `queryset.update()` goes around it.
        content = f"<div>before{bad_marker}after</div>"

        # An empty slot, and a log line -- degrading silently would hide a
        # broken page from whoever has to fix it.
        with self.assertLogs("core.html_widget", level="WARNING"):
            self.assertEqual(self.expand(content), "<div>beforeafter</div>")

    def test_one_broken_widget_does_not_take_the_others_with_it(self):
        content = f"<div>{marker(name='test-boom')}{marker()}</div>"

        with self.assertLogs("core.html_widget", level="WARNING"):
            self.assertEqual(self.expand(content), "<div><b>W</b></div>")

    # ------------------------------------------
    # Tests Recursion
    # ------------------------------------------

    def test_a_widget_rendering_a_marker_is_not_expanded_again(self):
        # This is what makes recursion structurally impossible: a single pass,
        # and the inserted HTML is never rescanned. No depth counter needed.
        content = f"<div>{marker(name='test-recursive')}</div>"

        self.assertEqual(
            self.expand(content),
            '<div><t-widget name="test-echo"></t-widget></div>',
        )

    def test_only_top_level_markers_are_expanded(self):
        # A nested marker is refused on save, but the renderer must not depend
        # on that: the outer marker's subtree is discarded, so splicing into it
        # would target a detached tree.
        content = f'<div><t-widget name="test-echo">{marker()}</t-widget></div>'

        self.assertEqual(self.expand(content), "<div><b>W</b></div>")
