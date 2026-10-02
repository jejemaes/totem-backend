import decimal
import typing as t

from django.test import SimpleTestCase
from ninja.errors import ConfigError

from core.api.validation import _check_derived_fields
from core.schemas import ModelSchema
from core.schemas.factory import create_schema
from core.schemas.utils import extract_orm_fields_map
from core.tests.computed_app.api import LineController, OrderController
from core.tests.computed_app.models import Line, Order
from core.tests.computed_app.schemas import OrderSchema
from core.tests.computed_app.services import LineService, OrderService
from totem.api import api_v1


class TestConversion(SimpleTestCase):
    """A derived field is converted as its `output_field`, always nullable."""

    def test_types(self):
        fields = OrderSchema.model_fields
        expected = {
            "line_count": t.Optional[int],               # stored, annotation
            "total": t.Optional[decimal.Decimal],        # stored, annotation
            "tag_names": t.Optional[str],                # stored, prefetch
            "label_upper": t.Optional[str],              # generated
            "line_count_virtual": t.Optional[int],       # virtual, annotation
            "max_quantity_virtual": t.Optional[int],     # virtual, prefetch
        }
        for name, annotation in expected.items():
            with self.subTest(name):
                self.assertEqual(fields[name].annotation, annotation)
                self.assertIsNone(fields[name].default)

    def test_labels_come_from_the_field_not_its_output_field(self):
        self.assertEqual(OrderSchema.model_fields["line_count"].title, "Line Count")
        self.assertEqual(OrderSchema.model_fields["label_upper"].title, "Label (Upper)")

    def test_values_are_validated_as_the_output_field(self):
        schema = OrderSchema(id="x", label="l", status="s", total="12.50", max_quantity_virtual=None)
        self.assertEqual(schema.total, decimal.Decimal("12.50"))

    def test_openapi(self):
        components = api_v1.get_openapi_schema()["components"]["schemas"]
        properties = next(
            c["properties"] for c in components.values()
            if "line_count_virtual" in c.get("properties", {})
        )
        # an integer -- bounded like the `IntegerField` it holds -- or null
        integer, null = properties["line_count_virtual"]["anyOf"]
        self.assertEqual((integer["type"], null["type"]), ("integer", "null"))
        self.assertIn("total", properties)


class TestSelection(SimpleTestCase):

    def test_virtual_fields_are_only_selected_by_name(self):
        everything = create_schema(Order, name="OrderEverything")
        self.assertIn("line_count", everything.model_fields)   # stored: a column
        self.assertIn("label_upper", everything.model_fields)  # generated: a column
        self.assertNotIn("line_count_virtual", everything.model_fields)

        excluded = create_schema(Order, name="OrderExcluded", exclude=["label"])
        self.assertNotIn("line_count_virtual", excluded.model_fields)

    def test_unknown_names_are_still_refused(self):
        with self.assertRaises(ConfigError):
            create_schema(Order, name="OrderUnknown", fields=["nope"])

    def test_virtual_fields_are_part_of_the_orm_fields_map(self):
        """So `_response_orm_fields` asks the service to load them."""
        fields_map = extract_orm_fields_map(OrderSchema, Order)
        self.assertIn("line_count_virtual", fields_map)
        self.assertIn("max_quantity_virtual", OrderController._response_orm_fields(OrderSchema))


class TestControllerValidation(SimpleTestCase):

    def fake_controller(self, model, service, **attributes):
        # borrowed, so it reads the fake's `model`
        attributes.setdefault("_response_orm_fields", classmethod(OrderController._response_orm_fields.__func__))
        return type("FakeController", (), {"model": model, "service": service, **attributes})

    def test_the_test_app_controllers_are_valid(self):
        for controller in (OrderController, LineController):
            with self.subTest(controller.__name__):
                self.assertEqual(list(_check_derived_fields(controller)), [])

    def test_derived_fields_refused_in_request_schemas(self):
        for name in ("line_count", "line_count_virtual", "label_upper"):
            with self.subTest(name):
                schema = create_schema(Order, name=f"OrderWrites_{name}", fields=["label", name])
                controller = self.fake_controller(Order, OrderService, create_request_schema=schema)
                (error,) = _check_derived_fields(controller)
                self.assertIn(f"{name} is a derived field", error)

    def test_virtual_field_through_a_relation_refused(self):
        class OrderVirtualSchema(ModelSchema):
            class Meta:
                model = Order
                fields = ["id", "line_count_virtual"]

        class LineWithVirtualSchema(ModelSchema):
            order: OrderVirtualSchema

            class Meta:
                model = Line
                fields = ["id", "order"]

        controller = self.fake_controller(Line, LineService, retrieve_response_schema=LineWithVirtualSchema)
        (error,) = _check_derived_fields(controller)
        self.assertIn("Order.line_count_virtual through 'order'", error)

    def test_ordering_by_a_virtual_field_refused(self):
        controller = self.fake_controller(Order, OrderService, list_ordering_fields=["-line_count_virtual"])
        (error,) = _check_derived_fields(controller)
        self.assertIn("'line_count_virtual', which is no column", error)
