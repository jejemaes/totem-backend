from asgiref.sync import async_to_sync
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from website.models import Widget
from website.schemas import WidgetCreateSchema, WidgetFilterSchema, WidgetUpdateSchema
from website.services import WidgetService


class TestWidgetService(TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(WidgetService)

    def _create(self, **kwargs):
        return async_to_sync(self.service.create)([WidgetCreateSchema(**kwargs)])[0]

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_a_custom_html_widget(self):
        widget = self._create(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>Hello</p>",
        )

        self.assertEqual(Widget.objects.get(pk=widget.pk).param_content, "<p>Hello</p>")

    def test_create_a_custom_html_widget_without_its_content_is_rejected(self):
        # The rule lives in `Widget.clean()`, which only a ModelForm ever calls:
        # every non-admin caller used to write straight past it.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self._create(
                title="Block", widget_type="custom_html", position="FOOTER_1"
            )

        self.assertIn("param_content", ctx.exception.dict()[0])
        self.assertFalse(Widget.objects.exists())

    def test_create_a_custom_html_widget_with_a_foreign_parameter_is_rejected(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self._create(
                title="Block", widget_type="custom_html", position="FOOTER_1",
                param_content="<p>Hello</p>", param_limit_item=3,
            )

        self.assertIn("param_limit_item", ctx.exception.dict()[0])

    def test_create_a_last_update_page_widget(self):
        widget = self._create(
            title="Latest", widget_type="last_update_page", position="HOMEPAGE_1",
            param_limit_item=5,
        )

        self.assertEqual(Widget.objects.get(pk=widget.pk).param_limit_item, 5)

    def test_create_a_last_update_page_widget_without_its_limit_is_rejected(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self._create(
                title="Latest", widget_type="last_update_page", position="HOMEPAGE_1"
            )

        self.assertIn("param_limit_item", ctx.exception.dict()[0])

    def test_two_widgets_on_the_same_position_are_rejected(self):
        self._create(
            title="First", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self._create(
                title="Second", widget_type="custom_html", position="FOOTER_1",
                param_content="<p>b</p>",
            )

        self.assertIn(
            "Another widget already occupies this position.",
            str(ctx.exception.dict()["__all__"]),
        )

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    def test_an_unknown_widget_type_is_rejected_by_the_schema(self):
        # `widget_type` carries `choices`, which the factory turns into an enum
        # built from the widget-type registry itself -- so the service's own
        # guard is unreachable over HTTP.
        with self.assertRaises(PydanticValidationError):
            WidgetCreateSchema(
                title="Block", widget_type="nope", position="FOOTER_1"
            )

    def test_an_unknown_position_is_rejected_by_the_schema(self):
        with self.assertRaises(PydanticValidationError):
            WidgetCreateSchema(
                title="Block", widget_type="custom_html", position="NOWHERE"
            )

    def test_an_unknown_widget_type_reaching_the_service_is_a_validation_error(self):
        # Reachable from a fixture or a data migration, where `Widget.clean()`
        # raises a bare `AttributeError` today: `get_widget_type` returns None
        # and the caller dereferences it.
        data = WidgetCreateSchema.model_construct(
            title="Block", widget_type="nope", position="FOOTER_1",
            param_content=None, param_limit_item=None,
        )

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([data])

        self.assertIn("widget_type", ctx.exception.dict()[0])

    def test_the_parameter_limit_upper_bound_is_rejected_by_the_schema(self):
        with self.assertRaises(PydanticValidationError):
            WidgetCreateSchema(
                title="Latest", widget_type="last_update_page",
                position="HOMEPAGE_1", param_limit_item=11,
            )

    def test_the_parameter_limit_lower_bound_is_rejected_by_the_schema(self):
        # Needs the `MinValueValidator(1)` on the model: with only a max,
        # `IntegerField` falls back to the connection range and `ge` is
        # -2147483648, so zero and negatives sail through.
        with self.assertRaises(PydanticValidationError):
            WidgetCreateSchema(
                title="Latest", widget_type="last_update_page",
                position="HOMEPAGE_1", param_limit_item=0,
            )

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_updating_the_type_revalidates_the_stored_parameters(self):
        # The key case for the merge: `update` passes only the fields actually
        # set, so `validate_data` receives `{"widget_type": ...}` alone and has
        # to check it against the parameters already on the row.
        widget = self._create(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": widget.pk},
                WidgetUpdateSchema(widget_type="last_update_page"),
            )

        errors = ctx.exception.dict()[widget.pk]
        self.assertIn("param_limit_item", errors)  # now required
        self.assertIn("param_content", errors)  # now forbidden

    def test_updating_the_type_and_its_parameters_together_is_accepted(self):
        # Also proves an explicit `None` survives `exclude_unset=True`.
        widget = self._create(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )

        async_to_sync(self.service.update)(
            {"id": widget.pk},
            WidgetUpdateSchema(
                widget_type="last_update_page",
                param_content=None,
                param_limit_item=3,
            ),
        )

        widget.refresh_from_db()
        self.assertEqual(widget.widget_type, "last_update_page")
        self.assertIsNone(widget.param_content)
        self.assertEqual(widget.param_limit_item, 3)

    def test_updating_the_title_alone_keeps_the_widget_valid(self):
        widget = self._create(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )

        async_to_sync(self.service.update)(
            {"id": widget.pk}, WidgetUpdateSchema(title="Renamed")
        )

        widget.refresh_from_db()
        self.assertEqual(widget.title, "Renamed")

    # ------------------------------------------
    # Tests Read / Delete
    # ------------------------------------------

    def test_read_filters_on_a_position_prefix(self):
        self._create(
            title="Footer", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )
        self._create(
            title="Home", widget_type="custom_html", position="HOMEPAGE_1",
            param_content="<p>b</p>",
        )

        queryset = async_to_sync(self.service.read)(
            WidgetFilterSchema(position_prefix="FOOTER_")
        )

        self.assertEqual([w.title for w in queryset], ["Footer"])

    def test_delete(self):
        widget = self._create(
            title="Block", widget_type="custom_html", position="FOOTER_1",
            param_content="<p>a</p>",
        )

        async_to_sync(self.service.delete)({"id": widget.pk})

        self.assertFalse(Widget.objects.filter(pk=widget.pk).exists())
