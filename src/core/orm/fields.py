from django.db import models
from django.utils.translation import gettext_lazy as _
from ulid import ULID

from core.orm.validators import HTML_DEFAULT_ATTRS, HTML_DEFAULT_TAGS, HTMLValidator


def generate_ulid() -> str:
    """Module-level function, and not a lambda: a field default must stay
    importable for the migration serializer.
    """
    return str(ULID())


class HtmlFieldMixin:
    default_error_messages = {
        "invalid": _(
            "The content must be a valid and parsable HTML code."
        ),
    }

    def __init__(
        self,
        *args,
        allow_javascript=False,
        allow_style_attr=True,
        allow_class_attr=True,
        allowed_tags=HTML_DEFAULT_TAGS,
        allowed_attrs=HTML_DEFAULT_ATTRS,
        **kwargs
    ):
        html_validator = HTMLValidator(
            allow_javascript=allow_javascript,
            allow_style_attr=allow_style_attr,
            allow_class_attr=allow_class_attr,
            allowed_tags=allowed_tags,
            allowed_attrs=allowed_attrs,
        )
        self.default_validators = [html_validator]

        super().__init__(*args, **kwargs)


class HtmlField(HtmlFieldMixin, models.TextField):
    description = _("Html")


class ULIDField(models.CharField):
    """A 26-character Crockford base32 ULID, meant to be used as a primary key.

    A `CharField` and not a `UUIDField`, even though a ULID is also 128 bits: the
    whole point of a ULID over a UUID4 is that it reads and sorts in creation
    order, and both properties only survive in the canonical 26-char form. Stored
    as a `uuid` column, every API client would get `018f...-...` back instead.
    """

    description = _("ULID")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 26)
        kwargs.setdefault("default", generate_ulid)
        kwargs.setdefault("editable", False)
        super().__init__(*args, **kwargs)
