from django.core.exceptions import ValidationError
from django.test import TestCase
from parameterized import parameterized

from core.orm import fields

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
                False,  # no root element
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
