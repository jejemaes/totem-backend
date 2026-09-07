from django.core.exceptions import ValidationError
from django.test import TestCase

from website.models import Widget
from website.website_widget import get_widget_type


class TestWidgetModel(TestCase):
    """`Widget.clean()`, the admin's validation path.

    The rule was extracted into `get_validation_errors` so the service can
    evaluate it on a dict of values; `is_valid` must keep behaving exactly as
    before for the ModelForm that calls it.
    """

    def test_clean_accepts_a_consistent_widget(self):
        widget = Widget(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )

        widget.clean()  # must not raise

    def test_clean_rejects_a_missing_required_parameter(self):
        widget = Widget(
            title="Block", widget_type="custom_html", position="FOOTER_1"
        )

        with self.assertRaises(ValidationError) as ctx:
            widget.clean()

        self.assertIn("param_content", ctx.exception.message_dict)

    def test_clean_rejects_a_foreign_parameter(self):
        widget = Widget(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>", param_limit_item=3,
        )

        with self.assertRaises(ValidationError) as ctx:
            widget.clean()

        self.assertIn("param_limit_item", ctx.exception.message_dict)

    def test_the_rule_reads_a_mapping_and_an_instance_alike(self):
        # The service holds a dict of internal values, the admin an instance.
        widget_type = get_widget_type("custom_html")
        instance = Widget(title="Block", widget_type="custom_html")
        values = {"widget_type": "custom_html", "param_content": None,
                  "param_limit_item": None}

        self.assertEqual(
            widget_type.get_validation_errors(instance),
            widget_type.get_validation_errors(values),
        )
