from django.db import models
from django.utils.translation import gettext_lazy as _

from core.orm.validators import HTML_DEFAULT_ATTRS, HTML_DEFAULT_TAGS, HTMLValidator


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
        allow_widget=False,
        allowed_tags=HTML_DEFAULT_TAGS,
        allowed_attrs=HTML_DEFAULT_ATTRS,
        **kwargs
    ):
        html_validator = HTMLValidator(
            allow_javascript=allow_javascript,
            allow_style_attr=allow_style_attr,
            allow_class_attr=allow_class_attr,
            allow_widget=allow_widget,
            allowed_tags=allowed_tags,
            allowed_attrs=allowed_attrs,
        )
        self.default_validators = [html_validator]

        super().__init__(*args, **kwargs)


class HtmlField(HtmlFieldMixin, models.TextField):
    description = _("Html")
