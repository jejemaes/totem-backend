import re

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _
from lxml import etree
from lxml import html as lxml_html
from lxml.html import defs


def validate_unique_choice_array(array):
    if len(list(array)) != len(set(array)):
        raise ValidationError(_("An element can only be once in the list."))


# ----------------------------------------------------------------------------
# HTML Validation
# ----------------------------------------------------------------------------

HTML_DEFAULT_ATTRS = defs.safe_attrs
HTML_DEFAULT_TAGS = (
    (defs.tags | defs.font_style_tags)
    - frozenset("style meta mark samp ruby cite map dir rp dfn bdo kbd".split())
    - defs.head_tags  # script, style, meta, link, ...
    - defs.frame_tags  # frameset, frame (but not iframe)
    - defs.deprecated_tags  # deprecated tags
    - defs.nonstandard_tags  # blink, marquee
    - defs.top_level_tags  # html, body, head, frameset
)


@deconstructible
class HTMLValidator:

    _style_re = re.compile(r"""([\w-]+)\s*:\s*((?:[^;"']|"[^";]*"|'[^';]*')+)""")

    _style_whitelist = [
        "font-size",
        "font-family",
        "font-weight",
        "font-style",
        "background-color",
        "color",
        "text-align",
        "line-height",
        "letter-spacing",
        "text-transform",
        "text-decoration",
        "text-decoration",
        "opacity",
        "float",
        "vertical-align",
        "display",
        "object-fit",
        "padding",
        "padding-top",
        "padding-left",
        "padding-bottom",
        "padding-right",
        "margin",
        "margin-top",
        "margin-left",
        "margin-bottom",
        "margin-right",
        "white-space",
        # appearance
        "background-image",
        "background-position",
        "background-size",
        "background-repeat",
        "background-origin",
        # box model
        "border",
        "border-color",
        "border-radius",
        "border-style",
        "border-width",
        "border-top",
        "border-bottom",
        "height",
        "width",
        "max-width",
        "min-width",
        "min-height",
        # tables
        "border-collapse",
        "border-spacing",
        "caption-side",
        "empty-cells",
        "table-layout",
    ]

    _style_whitelist.extend(
        [
            "border-%s-%s" % (position, attribute)
            for position in ["top", "bottom", "left", "right"]
            for attribute in ("style", "color", "width", "left-radius", "right-radius")
        ]
    )

    def __init__(
        self,
        allow_javascript=False,
        allow_style_attr=True,
        allow_class_attr=True,
        allowed_tags=HTML_DEFAULT_TAGS,
        allowed_attrs=HTML_DEFAULT_ATTRS,
    ):
        self.allow_javascript = allow_javascript
        self.allow_style_attr = allow_style_attr
        self.allow_class_attr = allow_class_attr
        self.allowed_tags = allowed_tags
        self.allowed_attrs = allowed_attrs

        if allow_javascript:
            self.allowed_attrs |= defs.event_attrs  # onmouse, onblur, onclick, ...
            self.allowed_tags |= {"script"}
        if allow_style_attr:
            self.allowed_attrs |= {"style"}

    def __call__(self, value):
        if not value:
            # Whether blank is acceptable is the field's business (`blank`), not
            # the validator's.
            return

        try:
            # The *HTML* parser, not `etree.fromstring`. HTML authored by a
            # human -- or emitted by a rich-text editor -- is not well-formed
            # XML: sibling top-level blocks, `<br>`, `&nbsp;` and comments are
            # all normal, and the XML parser rejected every one of them.
            # `create_parent` adds a synthetic root so a fragment with several
            # top-level elements parses; see `_validate_etree` about skipping it.
            root = lxml_html.fragment_fromstring(value, create_parent="div")
        except (etree.LxmlError, ValueError) as exc:
            raise ValidationError(
                _("Syntax error, this is not a parsable HTML code.")
            ) from exc

        rejected_tags, rejected_attrs, rejected_style_items, has_rejected_class = (
            self._validate_etree(root)
        )

        messages = []
        if rejected_tags:
            messages.append(_("Invalid tags: %s") % (",".join(rejected_tags)))
        if rejected_attrs:
            messages.append(_("Invalid attributes: %s") % (",".join(rejected_attrs)))
        if rejected_style_items:
            messages.append(
                _("Invalid style (attribute): %s") % (",".join(rejected_style_items))
            )
        if has_rejected_class:
            messages.append(str(_("'class' attribute is not allowed here.")))

        if messages:
            raise ValidationError("\n".join(messages))

    def _validate_etree(self, root):
        rejected_tags = set()
        rejected_attrs = set()
        rejected_style_items = set()
        has_rejected_class = False
        # `iterdescendants` and not `iter`: the root is the synthetic wrapper
        # added by `fragment_fromstring`, which is not authored content and must
        # not be checked against the allowlist.
        #
        # `etree.Element` restricts the walk to elements, so comments and
        # processing instructions never reach the tag check. Their `.tag` is a
        # *function*, not a string: it used to land in `rejected_tags` and make
        # `",".join(...)` raise `TypeError` -- a 500 -- instead of a
        # `ValidationError`. Comments are inert, so they are simply allowed.
        for node in root.iterdescendants(etree.Element):
            if node.tag not in self.allowed_tags:
                rejected_tags.add(node.tag)

            rejected_attrs |= set(node.attrib) - self.allowed_attrs

            if self.allow_style_attr:
                rejected_style_items |= self._validate_style_attribute(node)

            if not self.allow_class_attr:
                has_rejected_class |= "class" in node.attrib

        return rejected_tags, rejected_attrs, rejected_style_items, has_rejected_class

    def _validate_style_attribute(self, el):
        invalid_style = set()
        attributes = el.attrib
        styling = attributes.get("style")
        if styling:
            styles = self._style_re.findall(styling)
            for style in styles:
                if style[0].lower() not in self._style_whitelist:
                    invalid_style.add(style[0].lower())
        return invalid_style
