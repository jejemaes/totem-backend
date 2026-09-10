"""Themes: the visual identity a website is rendered with, and the layouts a page picks from.

A theme is **code, not a row**. It ships templates, a stylesheet and the options
it accepts, so it is deployed rather than inserted -- the same call
`core.html_widget` makes for widgets. Only the *selection* is data:
`Website.theme` holds an id, `Website.theme_options` the values, `Page.layout`
the structure of one page's body.

Rendering separates into three tiers, which is what keeps the cost of a new
theme independent of the number of content types:

* the **chrome** (`base_template`) belongs to the theme -- header, footer,
  assets, CSS variables. Every content template inherits it through a
  `{% extends %}` on a variable;
* the **layouts** (`layouts/<id>.html`) belong to the theme too, and a `Page`
  chooses among them;
* the **template of one record** (`event/event_detail.html`, say) belongs to the
  app that ships the model. It extends the theme's chrome and costs existing
  themes nothing. A theme that wants to restyle it may override it, which is
  `get_template_names`' second rung.

This module must not import models. It is loaded by
`autodiscover_modules('theme')` from `WebsiteConfig.ready()`, so anything it
imports is imported during app startup; keeping it model-free is what makes the
sweep insensitive to load order. `website.models` imports *from* here, never the
other way round.
"""

import logging
import re
import typing as t

from django.utils.safestring import SafeString, mark_safe
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError as PydanticValidationError

_logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Layout vocabulary
# ----------------------------------------------------------------------------

# A dict and not a set: the label is what a page editor shows in its dropdown,
# exactly as `AbstractHtmlWidget.title` is what the block list shows. It also
# hands `Page.layout` its `choices` with no second list to keep in sync.
#
# The vocabulary is CLOSED and shared by every theme; which layouts a theme
# actually implements is OPEN (`AbstractTheme.layouts`, with a render-time
# fallback). That asymmetry is the whole reason switching theme cannot
# invalidate a page.
#
# Adding an id later is backwards compatible -- existing themes simply do not
# implement it and fall back. Removing one is not. So this list stays short, and
# each entry earns its place: `full-width` is today's behaviour, `narrow` the
# readable single column, `sidebar-*` the slots a side-menu widget can live in,
# `landing` the one that does not render the page title.
LAYOUTS = {
    "full-width": "Full Width",
    "narrow": "Narrow Article",
    "sidebar-left": "Sidebar, Left",
    "sidebar-right": "Sidebar, Right",
    "landing": "Landing",
}

LAYOUT_DEFAULT = "full-width"

DEFAULT_THEME_ID = "default"


def get_layouts():
    """The vocabulary as (id, label) pairs, ordered by id so a listing is stable."""
    return sorted(LAYOUTS.items())


def get_layout_ids():
    return set(LAYOUTS)


def get_layout_choices():
    """`choices` for `Page.layout`.

    A callable, so django serializes it into a migration as an import reference
    and adding a layout generates none. Safe to evaluate whenever the schema
    factory asks -- unlike a theme id, this vocabulary is a module constant and
    is therefore complete on import, not filled by an autodiscovery pass.
    """
    return get_layouts()


# ----------------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------------

_REGISTRY = {}  # id -> theme instance


def get_theme(theme_id, raise_if_not_found=False):
    theme = _REGISTRY.get(theme_id)
    if theme is None and raise_if_not_found:
        raise ValueError(f"`{theme_id}` not found in the theme registry.")
    return theme


def get_themes():
    """Every registered theme, ordered by id so a listing is stable."""
    return [_REGISTRY[theme_id] for theme_id in sorted(_REGISTRY)]


def get_theme_choices():
    """(id, title) pairs -- for an admin form, NOT for `Website.theme`'s `choices`.

    Deliberately not wired onto the model field, and the reason is not the one
    about discovery order (this registry is filled in `WebsiteConfig.ready()`,
    which runs before `CoreConfig.ready()` builds the API schemas). It is that
    `core.schemas.fields` turns `choices` into a pydantic `Enum`, and that enum
    would sit in the *response* schema too: reading a website whose stored theme
    has since been deleted from the code would fail serialization instead of
    degrading. `WebsiteRenderContextMixin.get_theme` and `resolve_options` exist
    precisely so that a stale selection renders the default and logs, and an
    enum on the read path would defeat both.

    An admin form builds its dropdown from this instead, per request, well after
    startup.
    """
    return [(theme.id, theme.title) for theme in get_themes()]


class ThemeMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_cls = type.__new__(cls, name, bases, attrs)

        # The abstract base declares no id and is not a theme anybody can
        # select, so it is not registered.
        if new_cls.id is None:
            return new_cls

        if not new_cls.title:
            raise ValueError(
                f"Theme {new_cls.id!r} must have a title: it is what the editor "
                f"shows in the list of themes."
            )
        if new_cls.id in _REGISTRY:
            raise ValueError(f"{new_cls.id} is a theme already defined.")

        # The jinja loader is one flat search path, so template names are global
        # and the first app in `INSTALLED_APPS` wins a collision. Forcing the id
        # into the directory makes a collision require two themes claiming the
        # same id, which the check above already refuses. One cheap assertion
        # closes the only silent failure mode of a flat loader.
        if not new_cls.template_dir:
            raise ValueError(f"Theme {new_cls.id!r} must declare a `template_dir`.")
        if not new_cls.template_dir.rstrip("/").endswith(f"/{new_cls.id}"):
            raise ValueError(
                f"Theme {new_cls.id!r} has template_dir "
                f"{new_cls.template_dir!r}, which must end with '/{new_cls.id}' so "
                f"that two themes cannot resolve to the same templates."
            )

        unknown = set(new_cls.layouts) - get_layout_ids()
        if unknown:
            raise ValueError(
                f"Theme {new_cls.id!r} declares layouts not in the shared "
                f"vocabulary: {', '.join(sorted(unknown))}. Known layouts: "
                f"{', '.join(sorted(get_layout_ids()))}."
            )
        if new_cls.default_layout not in new_cls.layouts:
            raise ValueError(
                f"Theme {new_cls.id!r} has default_layout "
                f"{new_cls.default_layout!r}, which is not among the layouts it "
                f"implements ({', '.join(sorted(new_cls.layouts))}). It is the "
                f"fallback every unimplemented layout lands on, so it must exist."
            )

        # What makes `resolve_options` total. A required option would make
        # `option_schema()` raise, and then a stored blob that no longer matches
        # its schema would have no defaults to fall back to -- taking down every
        # page of the site rather than degrading, unlike a broken widget marker
        # which only blanks itself.
        required = [
            fname
            for fname, finfo in new_cls.option_schema.model_fields.items()
            if finfo.is_required()
        ]
        if required:
            raise ValueError(
                f"Theme {new_cls.id!r} declares option(s) with no default: "
                f"{', '.join(required)}. Every option must have one, so that the "
                f"read path can always fall back to `option_schema()`."
            )

        _REGISTRY[new_cls.id] = new_cls()
        return new_cls


def validate_themes():
    """Registry consistency, checked once at startup.

    Only in-process consistency, and only what is a pure code bug: the default
    theme must exist, because it is the last rung of every fallback chain.

    Deliberately does NOT check that each declared layout has a template file.
    The three-rung `get_layout_template_names` already degrades a missing file
    at render time, and `ready()` runs for every management command -- so
    logging an error there would put noise in front of the very `migrate` or
    `collectstatic` that a half-deployed theme needs.
    """
    if DEFAULT_THEME_ID not in _REGISTRY:
        raise ValueError(
            f"No theme registered under {DEFAULT_THEME_ID!r}. It is the last "
            f"fallback of every template lookup and of every unknown stored "
            f"selection, so the site cannot render without it. Registered: "
            f"{', '.join(sorted(_REGISTRY)) or 'none'}."
        )


# ----------------------------------------------------------------------------
# Option values that end up inside a <style>
# ----------------------------------------------------------------------------

# Constrained types a theme is expected to use for its options. Same idiom as
# `SideMenuWidget.Attributes.css_class`, except that there the pattern is
# hygiene and here it is the control: these values are author-supplied and land
# in a `<style>` element.
CssColor = t.Annotated[
    str,
    StringConstraints(pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"),
]
CssLength = t.Annotated[
    str, StringConstraints(pattern=r"^-?\d+(?:\.\d+)?(?:px|rem|em|%|vh|vw)$")
]
CssFontStack = t.Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z0-9 ,'\"-]{1,128}$")
]

# Every character a CSS *value* legitimately needs, and nothing else. The
# exclusions are the point:
#   `<` `>`  cannot write `</style` and close the element
#   `;`      cannot end this declaration and open another
#   `{` `}`  cannot escape the rule and add a selector
#   `:`      cannot write a `data:` url
#   `@`      no `@import`
#   `\`      no CSS unicode escape, which would reconstruct any of the above
#   `/`      no `//host/path` inside a `url()`
#
# `(` and `)` stay so that `rgba()` and `calc()` work, and that is the whole of
# the residual risk: ANY bare function name passes -- `url(x)`, `attr(x)`, even
# the long-dead `expression(...)`. Deliberately accepted, for two reasons.
#
# These values land in a *custom property*, which is only a token stream: it
# means nothing until the theme's own stylesheet substitutes it with `var()`
# into a real property, and a function invalid at that site makes the
# declaration invalid at computed-value time, which the browser drops.
# `expression()` in particular only ever ran in IE 10 and earlier, which had no
# custom properties at all. And with `/` and `:` excluded, the `x` in `url(x)`
# can only be a same-origin relative filename with no separator -- a request for
# a file that does not exist.
#
# So do not tighten this to reject function names: it would buy nothing and
# break `rgba()` and `calc()`, which themes need.
CSS_VALUE_RE = re.compile(r"^[A-Za-z0-9 #%,.()_'\"+-]{1,256}$")


class NoOptions(BaseModel):
    """Options of a theme that declares none.

    Defined here rather than imported from `core.html_widget`: that module's
    docstring establishes a one-way dependency rule, and the two registries stay
    independent of each other.
    """

    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------
# Theme class
# ----------------------------------------------------------------------------


class AbstractTheme(metaclass=ThemeMetaclass):
    id = None
    title = None

    # A directory, not a `{layout_id: path}` mapping. A mapping restates the id
    # in every path, so a typo becomes a permanent silent fallback, and it makes
    # "which layouts does this theme have" unanswerable from the filesystem.
    # A directory plus the `<template_dir>/layouts/<layout_id>.html` convention
    # lets `select_template` do the whole fallback with no code of ours.
    template_dir = None

    # The subset of `LAYOUTS` this theme implements. Declared even though the
    # filesystem already says, for two reasons: the API must answer "which
    # layouts may this page choose" without walking template directories, and a
    # typo'd id becomes a startup error instead of a permanent silent
    # degradation. `layouts` is the contract, `select_template` the mechanism.
    #
    # `frozenset` and not `set`/`list`: a mutable class default that a subclass
    # mutates in place would mutate the base.
    layouts = frozenset()

    # Rung two of the fallback chain, and so the "switching theme never breaks a
    # page" guarantee. A separate attribute rather than "the first of `layouts`":
    # a frozenset has no order, and *which one is the safe one* is the theme
    # author's decision, not something to infer.
    default_layout = LAYOUT_DEFAULT

    # Collected-static paths, rendered through the `static` jinja global. Held in
    # python rather than hardcoded in the template so `get_themes()` can answer
    # what a theme loads, and so swapping in a manifest storage needs no template
    # edit. Reserved for collected static: a CDN URL stays a literal tag in the
    # theme's own base.html, because `static()` on an absolute URL happens to
    # pass through today but a `ManifestStaticFilesStorage` would look it up and
    # raise.
    stylesheets = ()
    scripts = ()

    # The exact mirror of `AbstractHtmlWidget.attribute_schema`: it rejects a
    # malformed write, coerces values before rendering, and describes itself as
    # JSON Schema so the editor builds its form instead of restating it.
    option_schema: t.Type[BaseModel] = NoOptions

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    @property
    def base_template(self):
        """The theme's chrome, meant to be `{% extends %}`-ed -- by variable.

        Put in the render context so a template shipped by *any* app inherits
        this site's header, footer, assets and CSS variables without that app
        knowing a single theme id. This is what keeps a new content type at one
        file, and a new theme at zero files per content type.
        """
        return f"{self.template_dir}/base.html"

    def get_template_names(self, name):
        """Candidates for a template an app provides, most specific first.

        Two rungs, not three: the app's own template already extends
        `base_template`, so it is *already* themed and is the correct universal
        fallback. A default-theme rung in between would put the default theme's
        bespoke markup under the current theme's stylesheet -- the same
        cross-theme mixing `get_layout_template_names` refuses.
        """
        return [f"{self.template_dir}/{name}", name]

    def get_layout_template_names(self, layout_id):
        """Candidates for `layout_id`, most specific first.

        Three rungs, walked by `django.template.loader.select_template`, so the
        fallback is django's and there is no rung-walking code here to get wrong:

        1. the page's layout in this theme;
        2. this theme's own default -- the non-negotiable guarantee that
           switching theme never breaks a page;
        3. the default theme's default, the backstop for a theme whose files were
           lost in a deploy. Without it such a mistake is a 500 at render time,
           in a sync thread past the async phase and out of reach of any `try`
           the view could hold, on every page at once.

        An unknown `layout_id` needs no special case: rung one simply misses.
        That is the whole reason to resolve through the filesystem rather than a
        dict lookup.

        What it deliberately never does is fall from `sidebar-left` in this theme
        to `sidebar-left` in another: another theme's markup under this theme's
        stylesheet is worse than this theme's own default layout.
        """
        candidates = [
            f"{self.template_dir}/layouts/{layout_id}.html",
            f"{self.template_dir}/layouts/{self.default_layout}.html",
            f"website/themes/{DEFAULT_THEME_ID}/layouts/{LAYOUT_DEFAULT}.html",
        ]
        # De-duplicated: a theme whose layout *is* its default would otherwise
        # produce the same name twice, and `response.template_name` is what the
        # view tests assert on.
        seen = set()
        return [c for c in candidates if not (c in seen or seen.add(c))]

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    def validate_options(self, raw_options):
        """Coerce a raw options mapping into an `option_schema` instance.

        The write path. Raises `pydantic.ValidationError`, which the caller turns
        into whatever its layer reports -- exactly as
        `AbstractHtmlWidget.validate_attributes` prescribes.
        """
        return self.option_schema(**(raw_options or {}))

    def resolve_options(self, raw_options):
        """Same, but total: it never raises. The read path uses this one.

        Strict on write, tolerant on read. Two rungs, each with its own cause:

        1. keys absent from this schema are dropped silently. After a theme
           switch the stored blob describes the *previous* theme's options, and
           that is expected, not an error;
        2. anything left that still fails the schema falls back to
           `option_schema()` as a whole, with one log line. Whole-object and not
           field-by-field: rebuilding per field costs N constructions, and a blob
           failing its own schema is a data problem someone should see rather
           than something to half-salvage.
        """
        known = {
            key: value
            for key, value in (raw_options or {}).items()
            if key in self.option_schema.model_fields
        }
        try:
            return self.option_schema(**known)
        except PydanticValidationError as exc:
            _logger.warning(
                "Stored options of theme %r do not match its schema, falling back "
                "to defaults: %s",
                self.id,
                exc,
            )
            return self.option_schema()

    def css_variables(self, options):
        """The options as CSS custom property names and values.

        Overridable so a theme can derive values -- a hover shade from a base
        colour -- instead of asking the author for both.

        A `None` value means "not set" and is dropped: the theme's stylesheet
        declares every variable in `:root` with its own fallback, so the injected
        block is a diff. That is what makes an absent value degrade correctly
        with no code at all.
        """
        return {
            f"--t-{name.replace('_', '-')}": value
            for name, value in options.model_dump().items()
            if value is not None
        }

    def render_css_variables(self, options) -> SafeString:
        """The `<style>` body declaring this theme's options, or "".

        Refuses a value it cannot vouch for rather than escaping it, because a
        `<style>` cannot be escaped into safety: the HTML parser decodes no
        entities in there, so `django.utils.html.escape` would hand `&lt;` to the
        CSS parser and protect nothing, while the sequence that does matter --
        `</style` -- is not one escaping addresses. Jinja's autoescape is worse
        still: it would turn a legitimate quoted font name into `&#34;`, which
        CSS cannot read. So the value is validated in python and marked safe, and
        `CSS_VALUE_RE` is the entire injection surface of this feature.

        A value that fails is dropped and logged, and the stylesheet's own
        `:root` default stands. The other variables still render: one bad option
        must not blank the whole block, the same instinct as `expand_widgets`
        degrading a single widget.

        Variable *names* come from `option_schema.model_fields`, i.e. from code,
        so they need no validation.
        """
        declarations = []
        for name, value in self.css_variables(options).items():
            text = str(value)
            if not CSS_VALUE_RE.match(text):
                _logger.warning(
                    "Theme %r: refusing the value of %s, which is not a plain CSS "
                    "value: %r",
                    self.id,
                    name,
                    text,
                )
                continue
            declarations.append(f"  {name}: {text};")

        if not declarations:
            return mark_safe("")
        body = "\n".join(declarations)
        return mark_safe(f":root {{\n{body}\n}}")


# ----------------------------------------------------------------------------
# The default theme
# ----------------------------------------------------------------------------


class DefaultTheme(AbstractTheme):
    """The theme the site falls back on, and for now the only one.

    Registered here rather than shipped by its own app on purpose: it is rung
    three of every fallback chain and `validate_themes` requires it, so
    something the engine structurally depends on must not be uninstallable by
    editing `INSTALLED_APPS`. Another app may still contribute a theme -- the
    sweep looks for `<app>/theme.py` anywhere -- it just cannot take this one
    away.

    Its templates and stylesheet do not exist yet; they arrive when the current
    `website/jinja2/website/layout.html` is split into a real theme. Until then
    every lookup falls through the three rungs and the views keep their own
    `template_name`, which is why nothing here is load-bearing at render time.
    """

    id = DEFAULT_THEME_ID
    title = "Default"
    template_dir = f"website/themes/{DEFAULT_THEME_ID}"
    layouts = frozenset(LAYOUTS)
    default_layout = LAYOUT_DEFAULT
    stylesheets = (f"website/themes/{DEFAULT_THEME_ID}/theme.css",)
