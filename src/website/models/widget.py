from django.core import validators
from django.db import models

from core import fields
from website import choices
from website.website_widget import get_widget_type, get_widget_type_choices


class WidgetQueryset(models.QuerySet):

    async def get_widget_website_position(self, position):
        # Note: make sure the widgets are fetched only once and kept in cache
        async for widget in self:
            if widget.position == position: # unique constraint on position
                return widget
        return None


class Widget(models.Model):
    title = models.CharField(
        "Title", max_length=256, null=False, blank=False
    )
    widget_type = models.CharField(
        "Type", max_length=64, null=False, blank=False, choices=get_widget_type_choices,
    )
    position = models.CharField(
        "Position", max_length=64, null=False, blank=False, choices=choices.WidgetPosition.choices,
    )

    # parameters
    param_content = fields.HtmlField("HTML Content", null=True, blank=True)
    param_limit_item = models.IntegerField("Max Item to Display", null=True, blank=True, validators=[validators.MaxValueValidator(10)], help_text="Used to limit the number of item to display in the widget.")

    @property
    def rendered_content(self):
        widget_type_instance = get_widget_type(self.widget_type)
        return widget_type_instance.render(self)

    objects = WidgetQueryset.as_manager()

    class Meta:
        verbose_name = "Widget"
        verbose_name_plural = "Widgets"
        constraints = [
            models.UniqueConstraint(
                fields=['position'], name='%(class)s_unique_position'
            ),
        ]

    # Native Overrides

    def clean(self):
        result = super().clean()

        widget_type_instance = get_widget_type(self.widget_type)
        widget_type_instance.is_valid(self, raise_exception=True)

        return result
