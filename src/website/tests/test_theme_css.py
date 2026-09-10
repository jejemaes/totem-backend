"""Theme options on their way into a `<style>` element.

Its own file because its subject is a security control, not a convenience:
`CSS_VALUE_RE` is the entire injection surface of the theme feature, since a
`<style>` cannot be escaped into safety -- the HTML parser decodes no entities
in there, so `escape()` protects nothing and breaks legitimate values, and the
sequence that ends the element (`</style`) is not one escaping addresses.
"""

from django.test import SimpleTestCase
from django.utils.safestring import SafeString
from parameterized import parameterized
from pydantic import BaseModel, ConfigDict

from website.theme import AbstractTheme, CssColor, CssLength


class CssTheme(AbstractTheme):
    id = "test-css"
    title = "CSS"
    template_dir = "core/themes/test-css"
    layouts = frozenset({"full-width"})
    default_layout = "full-width"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        color_primary: str = None
        font_size: str = None
        # `int` on purpose: `css_variables` stringifies, and a non-string value
        # must go through the same gate as everything else.
        weight: int = None

    option_schema = Options


class StrictTheme(AbstractTheme):
    """Uses the constrained types a theme is expected to declare."""

    id = "test-css-strict"
    title = "CSS Strict"
    template_dir = "core/themes/test-css-strict"
    layouts = frozenset({"full-width"})
    default_layout = "full-width"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        color_primary: CssColor = None
        size: CssLength = None

    option_schema = Options


class TestRenderCssVariables(SimpleTestCase):

    theme = CssTheme()

    def render(self, **values):
        return self.theme.render_css_variables(self.theme.option_schema(**values))

    def test_an_option_becomes_a_custom_property(self):
        css = self.render(color_primary="#c0392b")

        self.assertIn("--t-color-primary: #c0392b;", css)
        self.assertTrue(css.startswith(":root {"))

    def test_the_name_is_kebab_cased_from_the_field(self):
        self.assertIn("--t-font-size: 14px;", self.render(font_size="14px"))

    def test_an_unset_option_emits_nothing(self):
        """Absent means "don't emit", so the stylesheet's own `:root` stands.

        That is what makes a missing value degrade with no code at all, and why
        `None` is the canonical default for a theme option.
        """
        css = self.render(color_primary="#fff")

        self.assertIn("--t-color-primary", css)
        self.assertNotIn("--t-font-size", css)

    def test_all_options_unset_renders_the_empty_string(self):
        """So the template's `{% if theme_style %}` omits the `<style>` entirely."""
        self.assertEqual(self.render(), "")

    def test_the_result_is_marked_safe(self):
        self.assertIsInstance(self.render(color_primary="#fff"), SafeString)

    def test_a_non_string_value_still_renders(self):
        self.assertIn("--t-weight: 700;", self.render(weight=700))

    @parameterized.expand([
        ("closes_the_declaration", "red;}"),
        ("closes_the_element", "red</style><script>alert(1)</script>"),
        ("adds_a_declaration", "red;background:url(//evil/x)"),
        ("css_unicode_escape", r"\3c /style"),
        ("at_import", "@import url(//evil)"),
        ("adds_a_selector", "red}\n:root{--x:y"),
        ("data_url", "url(data:text/html;base64,x)"),
        ("too_long", "a" * 300),
        ("newline", "red\nbackground: blue"),
        ("colon", "a:b"),
    ])
    def test_a_value_that_is_not_a_plain_css_value_is_dropped(self, name, value):
        with self.assertLogs("website.theme", level="WARNING"):
            css = self.render(color_primary=value, font_size="14px")

        self.assertNotIn("--t-color-primary", css)
        # The other variables still render: one bad option must not blank the
        # whole block, the same instinct as a broken widget marker only blanking
        # itself.
        self.assertIn("--t-font-size: 14px;", css)

    @parameterized.expand([
        ("url", "url(x)"),
        ("attr", "attr(data-x)"),
        ("legacy_expression", "expression(alert(1))"),
    ])
    def test_a_bare_function_name_passes_and_that_is_accepted(self, name, value):
        """The documented residual, pinned so it is a decision and not a surprise.

        `(` and `)` have to stay for `rgba()` and `calc()`, so any bare function
        name gets through. It is inert: the value lands in a custom property,
        which is only a token stream until the theme's own stylesheet substitutes
        it with `var()` into a real property -- and a function invalid at that
        site makes the declaration invalid at computed-value time, which the
        browser drops. `expression()` only ever ran in IE 10 and earlier, which
        had no custom properties. With `/` and `:` excluded, `url(x)` can only
        name a same-origin file with no path separator.

        This test exists so that nobody tightens the gate to reject function
        names and breaks `rgba()` on the way.
        """
        css = self.render(color_primary=value)

        self.assertIn(f"--t-color-primary: {value};", css)

    def test_a_quoted_font_stack_survives(self):
        """The reason this validates instead of escaping.

        Jinja's autoescape would turn this into `&#34;Helvetica Neue&#34;`, which
        the CSS parser cannot read.
        """
        css = self.theme.render_css_variables(
            self.theme.option_schema(font_size='"Helvetica Neue", sans-serif')
        )

        self.assertIn('--t-font-size: "Helvetica Neue", sans-serif;', css)

    def test_rgba_and_calc_survive(self):
        css = self.render(color_primary="rgba(192, 57, 43, 0.5)", font_size="calc(1rem + 2px)")

        self.assertIn("--t-color-primary: rgba(192, 57, 43, 0.5);", css)
        self.assertIn("--t-font-size: calc(1rem + 2px);", css)


class TestResolveOptions(SimpleTestCase):
    """The read path, which must never raise."""

    theme = CssTheme()

    def test_none_and_empty_give_the_defaults(self):
        for raw in (None, {}):
            self.assertIsNone(self.theme.resolve_options(raw).color_primary)

    def test_a_valid_blob_is_coerced(self):
        options = self.theme.resolve_options({"color_primary": "#fff"})

        self.assertEqual(options.color_primary, "#fff")

    def test_keys_of_another_theme_are_dropped_silently(self):
        """What a theme switch leaves behind, and it is expected, not an error."""
        options = self.theme.resolve_options(
            {"color_primary": "#fff", "some_other_theme_option": "x"}
        )

        self.assertEqual(options.color_primary, "#fff")

    def test_a_value_failing_the_schema_falls_back_whole_and_logs(self):
        strict = StrictTheme()

        with self.assertLogs("website.theme", level="WARNING"):
            options = strict.resolve_options({"color_primary": "not-a-colour", "size": "2rem"})

        # Whole-object fallback, deliberately: a blob failing its own schema is a
        # data problem someone should see in the log, not something to
        # half-salvage at the cost of N constructions.
        self.assertIsNone(options.color_primary)
        self.assertIsNone(options.size)

    def test_the_write_path_still_refuses_it(self):
        """Strict on write, total on read -- that split is the point."""
        from pydantic import ValidationError as PydanticValidationError

        with self.assertRaises(PydanticValidationError):
            StrictTheme().validate_options({"color_primary": "not-a-colour"})

    def test_the_write_path_refuses_an_unknown_option(self):
        """`extra="forbid"`, so the editor gets a real error on a typo."""
        from pydantic import ValidationError as PydanticValidationError

        with self.assertRaises(PydanticValidationError):
            self.theme.validate_options({"nope": 1})
