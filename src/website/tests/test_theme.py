"""The theme registry, its metaclass checks and its template resolution.

Themes registered for the whole process, like the test widgets in
`core.tests.test_html_widget` and for the same reason: the registry is
module-level state filled at import, so a test theme has to be declared the way
a real one is. Their ids are prefixed `test-` so nothing in the project can
reference them.
"""

from django.test import SimpleTestCase
from django.utils.safestring import SafeString
from parameterized import parameterized
from pydantic import BaseModel, ConfigDict

from website.theme import (
    DEFAULT_THEME_ID,
    LAYOUT_DEFAULT,
    LAYOUTS,
    AbstractTheme,
    get_layout_choices,
    get_layouts,
    get_theme,
    get_theme_choices,
    get_themes,
    validate_themes,
)


class PartialTheme(AbstractTheme):
    """Deliberately incomplete: it implements two layouts out of five.

    Rung two of the fallback chain -- "switching theme never breaks a page" --
    has no other caller until a second real theme exists, so this is what
    exercises it.
    """

    id = "test-partial"
    title = "Partial"
    template_dir = "core/themes/test-partial"
    layouts = frozenset({"full-width", "narrow"})
    default_layout = "narrow"


class OptionsTheme(AbstractTheme):
    id = "test-options"
    title = "With Options"
    template_dir = "core/themes/test-options"
    layouts = frozenset({"full-width"})
    default_layout = "full-width"

    class Options(BaseModel):
        model_config = ConfigDict(extra="forbid")

        color_primary: str = None
        font_size: str = None

    option_schema = Options


class TestThemeRegistry(SimpleTestCase):

    def test_a_theme_is_registered_under_its_id(self):
        # The registry holds the instance the metaclass built, and callers only
        # ever reach a theme through `get_theme` -- a theme is not a singleton,
        # so identity against a fresh `PartialTheme()` would be the wrong
        # assertion.
        self.assertIsInstance(get_theme("test-partial"), PartialTheme)

    def test_an_unknown_id_is_none(self):
        self.assertIsNone(get_theme("test-nope"))

    def test_an_unknown_id_can_raise_instead(self):
        with self.assertRaises(ValueError):
            get_theme("test-nope", raise_if_not_found=True)

    def test_the_abstract_base_is_not_registered(self):
        self.assertNotIn(None, [theme.id for theme in get_themes()])
        self.assertIsNone(AbstractTheme.id)

    def test_the_listing_is_ordered_by_id(self):
        ids = [theme.id for theme in get_themes()]

        self.assertEqual(ids, sorted(ids))

    def test_the_default_theme_is_registered(self):
        """`validate_themes` depends on it, and so does every fallback chain."""
        self.assertIsNotNone(get_theme(DEFAULT_THEME_ID))
        validate_themes()  # must not raise

    def test_choices_pair_the_id_with_the_title(self):
        self.assertIn(("test-partial", "Partial"), get_theme_choices())


class TestThemeMetaclassChecks(SimpleTestCase):
    """Each check here removes a silent failure mode, so each gets a test."""

    def test_a_theme_must_have_a_title(self):
        with self.assertRaises(ValueError):
            type("T", (AbstractTheme,), {"id": "test-untitled", "title": ""})

    def test_two_themes_cannot_share_an_id(self):
        with self.assertRaisesMessage(ValueError, "already defined"):
            type("T", (AbstractTheme,), {"id": "test-partial", "title": "Dup"})

    def test_the_template_dir_is_required(self):
        with self.assertRaisesMessage(ValueError, "template_dir"):
            type("T", (AbstractTheme,), {"id": "test-nodir", "title": "No Dir"})

    def test_the_template_dir_must_end_with_the_id(self):
        """The jinja loader is one flat search path, so names are global.

        Forcing the id into the path makes a collision require two themes with
        the same id, which the registry already refuses.
        """
        with self.assertRaisesMessage(ValueError, "must end with"):
            type("T", (AbstractTheme,), {
                "id": "test-mismatch",
                "title": "Mismatch",
                "template_dir": "website/themes/somewhere-else",
            })

    def test_a_layout_outside_the_vocabulary_is_refused(self):
        with self.assertRaisesMessage(ValueError, "not in the shared"):
            type("T", (AbstractTheme,), {
                "id": "test-badlayout",
                "title": "Bad Layout",
                "template_dir": "core/themes/test-badlayout",
                "layouts": frozenset({"sidebar-middle"}),
            })

    def test_the_default_layout_must_be_implemented(self):
        with self.assertRaisesMessage(ValueError, "not among the layouts"):
            type("T", (AbstractTheme,), {
                "id": "test-baddefault",
                "title": "Bad Default",
                "template_dir": "core/themes/test-baddefault",
                "layouts": frozenset({"narrow"}),
                "default_layout": "full-width",
            })

    def test_an_option_without_a_default_is_refused(self):
        """The check that makes `resolve_options` total.

        A required option would make `option_schema()` raise, leaving stale
        stored options with nothing to fall back to -- and that would take down
        every page of the site, unlike a broken widget marker which only blanks
        itself.
        """
        class Required(BaseModel):
            model_config = ConfigDict(extra="forbid")
            color: str

        with self.assertRaisesMessage(ValueError, "no default"):
            type("T", (AbstractTheme,), {
                "id": "test-required-option",
                "title": "Required Option",
                "template_dir": "core/themes/test-required-option",
                "layouts": frozenset({"full-width"}),
                "option_schema": Required,
            })


class TestLayoutVocabulary(SimpleTestCase):

    def test_the_default_layout_is_in_the_vocabulary(self):
        self.assertIn(LAYOUT_DEFAULT, LAYOUTS)

    def test_the_vocabulary_is_pairs_ordered_by_id(self):
        pairs = get_layouts()

        self.assertEqual(pairs, sorted(pairs))
        self.assertIn((LAYOUT_DEFAULT, LAYOUTS[LAYOUT_DEFAULT]), pairs)

    def test_the_field_choices_are_the_vocabulary(self):
        """A callable, so a new layout generates no migration."""
        self.assertEqual(get_layout_choices(), get_layouts())


class TestTemplateResolution(SimpleTestCase):

    # Through the registry, the way every caller gets a theme.
    theme = get_theme("test-partial")

    def test_the_chrome_is_named_after_the_theme(self):
        self.assertEqual(
            self.theme.base_template, "core/themes/test-partial/base.html"
        )

    def test_an_app_template_resolves_in_two_rungs(self):
        """The theme's override, then the app's own -- which is already themed.

        The contract a future app shipping its own content type consumes, so it
        is pinned before one exists.
        """
        self.assertEqual(
            self.theme.get_template_names("event/event_detail.html"),
            [
                "core/themes/test-partial/event/event_detail.html",
                "event/event_detail.html",
            ],
        )

    def test_an_implemented_layout_resolves_to_itself_first(self):
        names = self.theme.get_layout_template_names("full-width")

        self.assertEqual(names[0], "core/themes/test-partial/layouts/full-width.html")

    def test_an_unimplemented_layout_falls_back_to_the_theme_default(self):
        """Rung two, and the reason switching theme cannot invalidate a page."""
        names = self.theme.get_layout_template_names("sidebar-left")

        self.assertEqual(
            names,
            [
                "core/themes/test-partial/layouts/sidebar-left.html",
                "core/themes/test-partial/layouts/narrow.html",
                f"website/themes/{DEFAULT_THEME_ID}/layouts/{LAYOUT_DEFAULT}.html",
            ],
        )

    def test_an_unknown_layout_needs_no_special_case(self):
        """Rung one simply misses -- which is why resolution goes by filesystem."""
        names = self.theme.get_layout_template_names("no-such-layout")

        self.assertEqual(len(names), 3)
        self.assertEqual(names[0], "core/themes/test-partial/layouts/no-such-layout.html")

    def test_the_candidate_list_is_deduplicated(self):
        """`response.template_name` is what the view tests assert on."""
        names = self.theme.get_layout_template_names("narrow")

        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[0], "core/themes/test-partial/layouts/narrow.html")


class TestDefaultThemeStylesheet(SimpleTestCase):
    """The default theme's options and its stylesheet have to agree.

    `render_css_variables` emits `--t-<kebab-cased-field>` for every option that
    is set, and `theme.css` is what gives each of those a fallback value in
    `:root` -- that pairing is the whole reason an unset option costs nothing.
    Renaming an option without touching the stylesheet would break it silently:
    the injected block would declare a variable no rule reads, and the value the
    author chose would simply have no effect.
    """

    def test_every_option_has_a_variable_declared_in_the_stylesheet(self):
        from pathlib import Path

        import website

        theme = get_theme(DEFAULT_THEME_ID)
        stylesheet = (
            Path(website.__file__).parent / "static" / theme.stylesheets[0]
        ).read_text()

        # All of them set, so `css_variables` emits every one.
        options = theme.option_schema(
            color_primary="#123456",
            color_body_bg="#000000",
            font_family_base="Lato, sans-serif",
            content_max_width="40rem",
        )

        for name in theme.css_variables(options):
            with self.subTest(variable=name):
                self.assertIn(f"{name}:", stylesheet)
