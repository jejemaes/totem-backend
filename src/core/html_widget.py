"""HTML widgets: the blocks a marker inside an `HtmlField` expands to.

A widget is referenced from the content by an inert marker element and rendered
server side:

    <t-widget name="last-page" attrs='{"limit":5}'></t-widget>

It has no database row of its own -- the parameters travel inline with the
marker. That is what lets the same kind of widget appear twice on a page with
different parameters, which a shared row could not express.

The marker format is defined here rather than in `core.orm.validators`, even
though the validator is what enforces it: the format belongs to the widget
subsystem, and putting it here keeps the dependency pointing one way. The
validator imports from this module; this module must never import the validator.

Every widget also renders with a stable CSS class, `t-widget t-widget-<id>`,
injected into its template context by `render`. Since a theme may not override a
widget's template, that class is the whole contract between the two: the widget
owns its markup, the theme owns how it looks. Inner parts follow the same
prefix, `t-widget-<id>__<part>`, written by hand in each template.
"""

import json
import logging
import typing as t

from django.template.loader import render_to_string
from django.utils.safestring import SafeString, mark_safe
from lxml import etree
from lxml import html as lxml_html
from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError

_logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Marker format
# ----------------------------------------------------------------------------

WIDGET_TAG = "t-widget"
WIDGET_NAME_ATTR = "name"
WIDGET_ATTRS_ATTR = "attrs"

# A page renders its widgets one at a time, so the cost is linear in their
# number. Bounded at write time, so a page cannot be authored into a
# performance cliff that only shows up in production.
WIDGET_MAX_COUNT = 20

# ----------------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------------

_REGISTRY = {}  # id -> widget instance


def get_widget(widget_id, raise_if_not_found=False):
    widget = _REGISTRY.get(widget_id)
    if widget is None and raise_if_not_found:
        raise ValueError(f"`{widget_id}` not found in the widget registry.")
    return widget


def get_widgets():
    """Every registered widget, ordered by id so a listing is stable."""
    return [_REGISTRY[widget_id] for widget_id in sorted(_REGISTRY)]


class HtmlWidgetMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_cls = type.__new__(cls, name, bases, attrs)

        # The abstract base declares no id and is not a widget anybody can
        # reference, so it is not registered.
        if new_cls.id is None:
            return new_cls

        # Checked on presence rather than on `hasattr`: the base class defines
        # both attributes, so `hasattr` is always true for a subclass and would
        # never catch anything.
        if not new_cls.title:
            raise ValueError(
                f"Widget {new_cls.id!r} must have a title: it is what the editor "
                f"shows in the list of blocks."
            )
        if new_cls.id in _REGISTRY:
            raise ValueError(f"{new_cls.id} is a widget already defined.")

        _REGISTRY[new_cls.id] = new_cls()
        return new_cls


# ----------------------------------------------------------------------------
# Widget class
# ----------------------------------------------------------------------------


class NoAttributes(BaseModel):
    """Parameters of a widget that takes none."""

    model_config = ConfigDict(extra="forbid")


class AbstractHtmlWidget(metaclass=HtmlWidgetMetaclass):
    id = None
    title = None
    template_name = None
    template_engine = "jinja2"

    # A pydantic model describing the parameters carried by `attrs`. It does
    # three jobs: reject a malformed marker when the content is saved, coerce
    # the values before rendering, and describe itself as JSON Schema so the
    # editor can build the options form instead of restating it.
    #
    # A plain `BaseModel` and not `core.schemas.ModelSchema`, which needs a
    # django model in its `Meta` -- a widget has none.
    attribute_schema: t.Type[BaseModel] = NoAttributes

    @property
    def widget_css_class(self):
        """The stable class hook a theme styles this widget through.

        Themes may not override a widget template, so this string is the entire
        contract between a widget and a theme -- which is why it is computed
        from the id here rather than written by hand in each template, where a
        typo would be a silently unstyled block. It follows the *id*, so the
        widget registered as `last-page` is `t-widget-last-page` even though its
        template is called `last_update_page.html`.

        `t-` and not `widget-`, to match `WIDGET_TAG` above: one prefix shared by
        the markup an author writes and the CSS a theme writes, so `grep
        t-widget` finds both.
        """
        return f"t-widget t-widget-{self.id}"

    def validate_attributes(self, raw_attributes):
        """Coerce a raw `attrs` mapping into an `attribute_schema` instance.

        Raises `pydantic.ValidationError`, which the caller turns into whatever
        its layer reports.
        """
        return self.attribute_schema(**(raw_attributes or {}))

    async def render(self, attributes, env) -> SafeString:
        """The widget's HTML.

        `attributes` is a validated `attribute_schema` instance, `env` the
        service environment. Everything this widget needs from the database is
        read here, in the caller's async phase and through the services -- never
        while a template renders, where a query would escape both the service
        layer and its access rules.

        One call is all `expand_widgets` needs; subclasses normally override
        `get_render_context` and leave this alone.
        """
        context = await self.get_render_context(attributes, env)
        # The theme's only hook into this widget, so it is not the widget's to
        # forget. Unconditional rather than `setdefault`: the hook is a contract,
        # and a widget wanting *extra* classes has its own attribute for that
        # (`SideMenuWidget.Attributes.css_class`). A widget overriding `render`
        # bypasses this, which is fine -- it renders no template.
        context["widget_css_class"] = self.widget_css_class
        return mark_safe(
            render_to_string(
                self.template_name, context, using=self.template_engine
            )
        )

    async def get_render_context(self, attributes, env):
        raise NotImplementedError(
            "A widget class must implement the get_render_context method !"
        )


# ----------------------------------------------------------------------------
# Expansion
# ----------------------------------------------------------------------------


async def expand_widgets(content, env) -> SafeString:
    """`content` with every widget marker replaced by its rendered HTML.

    Must be awaited from the caller's async phase, never from a template: the
    template renders in a thread with no running event loop, where an ORM call
    silently succeeds outside the service layer and its access rules.

    A single pass, and the inserted HTML is never rescanned -- which is what
    makes a widget rendering a marker unable to recurse.

    A widget that is unknown, malformed or raises becomes an empty slot and a
    log line. One broken widget must not take the page down with it.
    """
    if not content:
        return mark_safe("")

    # Cheap short-circuit: the overwhelmingly common case is content with no
    # marker at all, and it should cost nothing but this substring search.
    if WIDGET_TAG not in content:
        return mark_safe(content)

    try:
        root = lxml_html.fragment_fromstring(content, create_parent="div")
    except (etree.LxmlError, ValueError):
        _logger.warning("Could not parse HTML content to expand its widgets.")
        return mark_safe(content)

    # Only top-level markers. A nested one is refused when the content is
    # saved, but validation is write-time only and a fixture, a data migration
    # or a `queryset.update()` goes around it -- and a marker whose parent is
    # about to be replaced would be spliced into a detached tree.
    markers = [
        node
        for node in root.iter(WIDGET_TAG)
        if not any(
            ancestor.tag == WIDGET_TAG for ancestor in node.iterancestors()
        )
    ]

    for node in markers:
        _splice(node, await _render_marker(node, env))

    # Serialize the children, not the root: that root is the synthetic parent
    # added above to hold a fragment with several top-level elements.
    return mark_safe(
        (root.text or "")
        + "".join(
            lxml_html.tostring(child, encoding="unicode") for child in root
        )
    )


async def _render_marker(node, env) -> str:
    """The HTML a single marker expands to, or an empty string."""
    name = (node.get(WIDGET_NAME_ATTR) or "").strip()
    widget = get_widget(name)
    if widget is None:
        _logger.warning("Unknown widget %r in HTML content, rendered empty.", name)
        return ""

    raw_attributes = node.get(WIDGET_ATTRS_ATTR)
    try:
        parsed = json.loads(raw_attributes) if raw_attributes else {}
        if not isinstance(parsed, dict):
            raise ValueError("widget attributes must be a JSON object")
        attributes = widget.validate_attributes(parsed)
    except (ValueError, PydanticValidationError):
        _logger.warning(
            "Invalid parameters for widget %r, rendered empty.", name, exc_info=True
        )
        return ""

    try:
        return await widget.render(attributes, env)
    except Exception:  # pylint: disable=broad-except
        # A widget is content, and content must not be able to 500 a page.
        _logger.exception("Widget %r failed to render, rendered empty.", name)
        return ""


def _splice(node, markup):
    """Replace `node` by `markup`, preserving the text around it.

    lxml keeps the text that follows an element on that element (`tail`) and
    the text that opens a parent on the parent (`text`), so a naive `replace`
    loses or duplicates it. Covered by tests for a marker alone, surrounded by
    text, first, last, inside a paragraph, and for markup that is several
    blocks, plain text, or empty.
    """
    fragment = lxml_html.fragment_fromstring(markup or "", create_parent="div")
    parent = node.getparent()
    index = parent.index(node)
    children = list(fragment)

    def push_text(text):
        if not text:
            return
        if index == 0:
            parent.text = (parent.text or "") + text
        else:
            previous = parent[index - 1]
            previous.tail = (previous.tail or "") + text

    # Text opening the rendered markup has no element of its own to sit on.
    push_text(fragment.text)

    # The marker's own tail has to end up after everything inserted.
    if children:
        children[-1].tail = (children[-1].tail or "") + (node.tail or "")
    else:
        push_text(node.tail)

    for offset, child in enumerate(children):
        parent.insert(index + offset, child)
    parent.remove(node)
