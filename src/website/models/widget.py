from django.core import validators
from django.db import models

from core.orm import fields
from website import choices
from website.website_widget import get_widget_type, get_widget_type_choices


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
    # `MinValueValidator` is not cosmetic: `IntegerField` only appends the
    # connection range validator when no tighter one exists, so with the max
    # alone the generated schema is `ge=-2147483648` and `param_limit_item=0`
    # passes both validation and the database.
    param_limit_item = models.IntegerField("Max Item to Display", null=True, blank=True, validators=[validators.MinValueValidator(1), validators.MaxValueValidator(10)], help_text="Used to limit the number of item to display in the widget.")

    # No `rendered_content` property: a model property that renders a template
    # and silently needs unfetched database state is what made the render-time
    # queries invisible. `RendererWidgetRegistry` calls the widget type
    # directly, with data read in the view's async phase.

    class Meta:
        verbose_name = "Widget"
        verbose_name_plural = "Widgets"
        constraints = [
            models.UniqueConstraint(
                fields=['position'],
                name='%(class)s_unique_position',
                violation_error_message="Another widget already occupies this position.",
            ),
        ]

    # Native Overrides

    def clean(self):
        result = super().clean()

        widget_type_instance = get_widget_type(self.widget_type)
        widget_type_instance.is_valid(self, raise_exception=True)

        return result
