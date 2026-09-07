from collections import abc

from django.core import exceptions
from django.db import models
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe


_REGISTRY = {}  # widget_type -> instance of Widget Type


def get_widget_type_choices():
    return {widget_type.widget_type: widget_type.widget_type_name for widget_type in _REGISTRY.values() if widget_type.widget_type is not None}

def get_widget_type(widget_type, raise_if_not_found=False):
    widget_type_instance = _REGISTRY.get(widget_type)
    if widget_type_instance is None and raise_if_not_found:
        raise ValueError(f"`{widget_type}` not found in registry.")
    return widget_type_instance

#--------------------------------------------
# Widget Lazy Render Registry
#--------------------------------------------

class RendererWidgetRegistry:
    """Rendered widget HTML by position, for the template.

    Holds materialized widgets and their pre-resolved render data, because
    `__getitem__` runs while the template renders -- out of reach of any
    `sync_to_async` hop a service could open, and out of reach of the access
    rules. Nothing in here may touch the database.

    Build it with `WidgetService.read_render_registry`.
    """

    def __init__(self, widgets, render_data=None):
        if isinstance(widgets, (models.QuerySet, models.Manager)):
            # It used to take the queryset and iterate it lazily, from the
            # template. Refusing it here is what keeps that from coming back.
            raise TypeError(
                "RendererWidgetRegistry needs materialized widgets, not a lazy "
                f"{type(widgets).__name__}: it is consumed during template "
                "rendering. Use `WidgetService.read_render_registry()`."
            )
        self._widgets_by_position = {widget.position: widget for widget in widgets}
        self._render_data = render_data or {}

    def __getitem__(self, position):
        widget = self._widgets_by_position.get(position)
        if widget is None:
            return ''

        widget_type_instance = get_widget_type(widget.widget_type)
        if widget_type_instance is None:
            # A stale `widget_type` in the database is an empty slot, not a 500
            # halfway through the page.
            return ''

        return widget_type_instance.render(
            widget, self._render_data.get(widget.pk) or {}
        )

#--------------------------------------------
# Widget Type Class
#--------------------------------------------

class WebsiteWidgetMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_cls = type.__new__(cls, name, bases, attrs)
        for attr in ['widget_type', 'widget_type_name']:
            if not hasattr(new_cls, attr):
                raise ValueError(f"`{attr}` must be set when implementing a widget type class !")
        if new_cls.widget_type and new_cls.widget_type in _REGISTRY:
            raise ValueError(f"{new_cls.widget_type} is a widget type already defined.")

        _REGISTRY[new_cls.widget_type] = new_cls()
        return new_cls


class AbstractWebsiteWidget(metaclass=WebsiteWidgetMetaclass):
    widget_type = None
    widget_type_name = None
    template_name = None
    template_engine = 'jinja2'

    validation_required_fields = []

    async def aget_render_data(self, widget_instance, env):
        """Everything this widget type needs from the database.

        Called from the view's async phase, through the services, and handed
        back to `get_render_context` at render time. Default: nothing.
        """
        return {}

    def render(self, widget_instance, render_data=None):
        return mark_safe(render_to_string(
            self.template_name,
            self.get_render_context(widget_instance, render_data or {}),
            using=self.template_engine,
        ))

    def get_render_context(self, widget_instance, render_data):
        """The template context. Runs while the page renders: must not query."""
        raise NotImplementedError(
            "Widget Type class must implement the get_render_context method !"
        )

    def get_validation_errors(self, values):
        """Field name -> message, for the `param_*` fields this type rejects.

        `values` is a mapping of field name to value, which is what the service
        layer holds: `ServiceBase.validate_data` receives a dict of internal
        values, never a model instance. A model instance is accepted too and
        read through `getattr` -- that is what `Widget.clean()` passes.
        """
        if isinstance(values, abc.Mapping):
            read = values.get
        else:
            read = lambda fname: getattr(values, fname, None)  # noqa: E731

        errors = {}
        for fname in self.validation_required_fields:
            if read(fname) is None:
                errors[fname] = f"This field is required as the widget type is `{self.widget_type_name}`."

        # ensure other parameters field are set to None
        for fname in self.validation_null_fields:
            if read(fname) is not None:
                errors[fname] = f"This field must be unset as the widget type is `{self.widget_type_name}`."

        return errors

    def is_valid(self, widget_instance, raise_exception=False):
        errors = self.get_validation_errors(widget_instance)
        if errors:
            if raise_exception:
                raise exceptions.ValidationError(errors)
            return False
        return True

    @property
    def validation_null_fields(self):
        from website.models import Widget
        parameters_field_names = [f.name for f in Widget._meta.get_fields() if f.name.startswith('param_')]
        return list(set(parameters_field_names) - set(self.validation_required_fields))


class CustomHTMLWidget(AbstractWebsiteWidget):
    widget_type = 'custom_html'
    widget_type_name = "Custom HTML Block"
    template_name = "website/widgets/custom_html.html"

    validation_required_fields = ['param_content']

    def get_render_context(self, widget_instance, render_data):
        return {
            "title": widget_instance.title,
            "content": widget_instance.param_content,
        }


class LastUpdatePageWidget(AbstractWebsiteWidget):
    widget_type = 'last_update_page'
    widget_type_name = "Last Updated Page"
    template_name = "website/widgets/last_update_page.html"

    validation_required_fields = ['param_limit_item']

    async def aget_render_data(self, widget_instance, env):
        # Local import: `website.services` imports the models, which import this
        # module.
        from website.services import PageService

        queryset = await env.get(PageService).read_published(
            ordering=["-update_date"]
        )
        # `[0:None]` keeps the historical "no limit when unset" semantics.
        return {
            "pages": [
                page
                async for page in queryset[0:widget_instance.param_limit_item]
            ]
        }

    def get_render_context(self, widget_instance, render_data):
        return {
            "title": widget_instance.title,
            "pages": render_data.get("pages", ()),
        }
