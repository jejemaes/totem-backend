from django.core.exceptions import ValidationError
from django.test import TestCase
from parameterized import parameterized

from core.orm import fields
from core.orm.validators import HTMLValidator, WIDGET_MAX_COUNT

HTML_WITH_STYLE = """
<div id="root">
  <div id="products">
    <div class="product">
      <div id="product_name">Dark Red Energy Potion</div>
      <div id="product_price">$4.99</div>
      <div id="product_rate" style="font-size: 14px">4.7</div>
      <div id="product_description">Bring out the best in your gaming performance.</div>
    </div>
  </div>
</div>
"""


class TestHTMLField(TestCase):

    @parameterized.expand(
        [
            (False, "<p>this is a test</p>", True),
            (False, """<p onclick="alert('yolo')">this is a test</p>""", False),
            (True, """<p onclick="alert('yolo')">this is a test</p>""", True),
            (
                False,
                """<script>console.log('hi');</script><p onclick="alert('yolo')">this is a test</p>""",
                False,
            ),
            (
                True,
                """<script>console.log('hi');</script><p onclick="alert('yolo')">this is a test</p>""",
                True,  # sibling top-level blocks are normal HTML
            ),
            (
                True,
                """<div><script>console.log('hi');</script><p onclick="alert('yolo')">this is a test</p></div>""",
                True,
            ),
        ]
    )
    def test_allow_javascript(self, allow_javascript, value, is_valid):
        f = fields.HtmlField(allow_javascript=allow_javascript)

        if is_valid:
            self.assertEqual(f.clean(value, None), value)
        else:
            with self.assertRaises(ValidationError):
                f.clean(value, None)

    @parameterized.expand(
        [
            (False, "<p>this is a test</p>", True),
            (True, "<p>this is a test</p>", True),
            (False, HTML_WITH_STYLE, False),
            (True, HTML_WITH_STYLE, True),
            (True, """<p style="font-size: 14px">this is a test</p>""", True),
            (
                True,
                """<p style="font-size:">this is a test</p>""",
                True,
            ),  # valide key but no value
            (
                True,
                """<p style="not-existing: 14px">this is a test</p>""",
                False,
            ),  # invalid key
            (
                True,
                """<p style="border: something-strange">this is a test</p>""",
                True,
            ),  # valid key but non sense value: limitation since we don't check CSS validity.
        ]
    )
    def test_allow_style_attr(self, allow_style_attr, value, is_valid):
        f = fields.HtmlField(allow_style_attr=allow_style_attr)

        if is_valid:
            self.assertEqual(f.clean(value, None), value)
        else:
            with self.assertRaises(ValidationError):
                f.clean(value, None)

    @parameterized.expand(
        [
            (False, "<p>this is a test</p>", True),
            (True, "<p>this is a test</p>", True),
            (False, HTML_WITH_STYLE, False),
            (True, HTML_WITH_STYLE, True),
        ]
    )
    def test_allow_class_attr(self, allow_class_attr, value, is_valid):
        f = fields.HtmlField(allow_class_attr=allow_class_attr)

        if is_valid:
            self.assertEqual(f.clean(value, None), value)
        else:
            with self.assertRaises(ValidationError):
                f.clean(value, None)

    @parameterized.expand(
        [
            (fields.HTML_DEFAULT_TAGS, "<p>this is a test</p>", True),
            (fields.HTML_DEFAULT_TAGS - {"p"}, "<p>this is a test</p>", False),
            (fields.HTML_DEFAULT_TAGS, HTML_WITH_STYLE, True),
            (fields.HTML_DEFAULT_TAGS - {"div"}, HTML_WITH_STYLE, False),
        ]
    )
    def test_allowed_tags(self, allowed_tags, value, is_valid):
        f = fields.HtmlField(allowed_tags=allowed_tags)

        if is_valid:
            self.assertEqual(f.clean(value, None), value)
        else:
            with self.assertRaises(ValidationError):
                f.clean(value, None)

    @parameterized.expand(
        [
            (fields.HTML_DEFAULT_ATTRS, "<p>this is a test</p>", True),
            (fields.HTML_DEFAULT_ATTRS - {"id"}, "<p>this is a test</p>", True),
            (fields.HTML_DEFAULT_ATTRS, HTML_WITH_STYLE, True),
            (fields.HTML_DEFAULT_ATTRS - {"id"}, HTML_WITH_STYLE, False),
        ]
    )
    def test_allowed_attrs(self, allowed_attrs, value, is_valid):
        f = fields.HtmlField(allowed_attrs=allowed_attrs)

        if is_valid:
            self.assertEqual(f.clean(value, None), value)
        else:
            with self.assertRaises(ValidationError):
                f.clean(value, None)


class TestHTMLFieldParsing(TestCase):
    """What the field accepts as *shape*, independently of the allowlists.

    The validator used to parse with `lxml.etree`, the XML parser, so ordinary
    HTML was refused: sibling top-level blocks, an unclosed `<br>`, `&nbsp;`.
    Worse, a comment raised `TypeError` and an XML declaration `ValueError` --
    neither a `ValidationError`, so both surfaced as a 500 instead of a form
    error.
    """

    @parameterized.expand(
        [
            ("sibling top level blocks", "<p>a</p><p>b</p>"),
            ("html entity", "<div>a&nbsp;b</div>"),
            ("void element not self closed", "<div><br>text</div>"),
            ("comment", "<div>a<!-- an inert comment -->b</div>"),
            # With an `encoding` the XML parser raised `ValueError`, which the
            # `except XMLSyntaxError` did not catch -- so a 500, not a form error.
            ("xml declaration", '<?xml version="1.0" encoding="utf-8"?><div>x</div>'),
            ("bare text", "hello"),
        ]
    )
    def test_accepted_shapes(self, dummy, value):
        f = fields.HtmlField()

        # The validator never rewrites: what is given is what is stored.
        self.assertEqual(f.clean(value, None), value)

    @parameterized.expand(
        [
            ("script inside", "<div><script>alert(1)</script></div>"),
            # The synthetic parent added to support sibling blocks must not let
            # a top-level node escape the walk.
            ("script at top level", "<script>alert(1)</script>"),
            ("unknown attribute", '<div data-x="1">y</div>'),
            ("unknown tag", "<div><totem-widget/></div>"),
            ("style outside the whitelist", '<p style="not-existing: 14px">x</p>'),
        ]
    )
    def test_still_rejected(self, dummy, value):
        f = fields.HtmlField()

        with self.assertRaises(ValidationError):
            f.clean(value, None)

    @parameterized.expand([("empty", ""), ("none", None)])
    def test_the_validator_ignores_an_absent_value(self, dummy, value):
        # Tested on the validator and not through `Field.clean`: whether a blank
        # value is acceptable is decided by `null`/`blank` on the field, and the
        # validator must simply not choke on it.
        HTMLValidator()(value)  # must not raise

    def test_a_comment_never_crashes_the_validator(self):
        # Regression guard: `root.iter()` also yields comments, whose `.tag` is
        # the *function* `etree.Comment`. It landed in the rejected-tags set,
        # and `",".join(...)` then raised `TypeError`.
        f = fields.HtmlField()

        try:
            f.clean("<div><!-- x --></div>", None)
        except ValidationError:
            pass  # a verdict is acceptable; a TypeError is not


class TestHTMLFieldWidgetMarker(TestCase):
    """The `<t-widget>` marker, opted into per field with `allow_widget`.

    Only the *shape* is checked here: is the marker usable by the renderer at
    all. Whether `name` designates a known kind of widget, and whether `attrs`
    satisfies that kind's schema, belongs where the widget registry lives.
    """

    MARKER = '<div><t-widget name="last-page" attrs=\'{"limit":5}\'></t-widget></div>'

    def test_the_marker_is_refused_by_default(self):
        # `allow_widget` defaults to False, so the tag is simply not in the
        # allowlist: no separate rule needed to keep widgets out of a field that
        # never renders them.
        f = fields.HtmlField()

        with self.assertRaises(ValidationError):
            f.clean(self.MARKER, None)

    def test_the_marker_is_accepted_when_the_field_opts_in(self):
        f = fields.HtmlField(allow_widget=True)

        self.assertEqual(f.clean(self.MARKER, None), self.MARKER)

    def test_opting_in_does_not_widen_anything_else(self):
        f = fields.HtmlField(allow_widget=True)

        with self.assertRaises(ValidationError):
            f.clean('<div><t-widget name="x"/><script>alert(1)</script></div>', None)

    @parameterized.expand(
        [
            ("no attrs at all", '<div><t-widget name="x"></t-widget></div>'),
            ("self closing", '<div><t-widget name="x"/></div>'),
            ("empty attrs object", '<div><t-widget name="x" attrs=\'{}\'></t-widget></div>'),
            # Content between the tags is a fallback, kept for when the widget
            # is gone -- the renderer replaces it.
            ("fallback content", '<div><t-widget name="x"><p>fallback</p></t-widget></div>'),
            ("inside a paragraph", '<div><p>before <t-widget name="x"/> after</p></div>'),
        ]
    )
    def test_accepted_markers(self, dummy, value):
        f = fields.HtmlField(allow_widget=True)

        self.assertEqual(f.clean(value, None), value)

    @parameterized.expand(
        [
            ("attrs is not json", '<div><t-widget name="x" attrs="not json"></t-widget></div>'),
            ("attrs is not an object", '<div><t-widget name="x" attrs=\'[1,2]\'></t-widget></div>'),
            ("name is absent", "<div><t-widget></t-widget></div>"),
            ("name is blank", '<div><t-widget name="  "></t-widget></div>'),
        ]
    )
    def test_rejected_markers(self, dummy, value):
        f = fields.HtmlField(allow_widget=True)

        with self.assertRaises(ValidationError):
            f.clean(value, None)

    def test_a_marker_inside_a_marker_is_refused(self):
        # Not a safety problem -- expansion is single-pass, so it can neither
        # loop nor escape. But the renderer replaces the outer marker and
        # discards its subtree, so the inner one would silently vanish: better
        # said here than surprising at render time.
        f = fields.HtmlField(allow_widget=True)

        with self.assertRaises(ValidationError) as ctx:
            f.clean('<div><t-widget name="a"><t-widget name="b"/></t-widget></div>', None)

        self.assertIn("inside another widget", str(ctx.exception))

    def test_the_number_of_markers_is_bounded(self):
        # A page renders its widgets one at a time, so the cost is linear in
        # their number. The bound is what keeps a page from being authored into
        # a performance cliff.
        f = fields.HtmlField(allow_widget=True)
        marker = '<t-widget name="x"/>'

        f.clean(f"<div>{marker * WIDGET_MAX_COUNT}</div>", None)  # must not raise

        with self.assertRaises(ValidationError):
            f.clean(f"<div>{marker * (WIDGET_MAX_COUNT + 1)}</div>", None)

    def test_every_problem_is_reported_at_once(self):
        # The checks accumulate instead of stopping at the first: an author
        # fixing one message should not discover the next on the next save.
        f = fields.HtmlField(allow_widget=True)

        with self.assertRaises(ValidationError) as ctx:
            f.clean('<div><t-widget attrs="not json"/><span data-x="1"/></div>', None)

        self.assertEqual(len(ctx.exception.messages), 3)
