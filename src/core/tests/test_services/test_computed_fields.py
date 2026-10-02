from decimal import Decimal

from asgiref.sync import async_to_sync
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from core.tests.computed_app.models import Line, Order, Product, Tag
from core.tests.computed_app.schemas import (
    LineCreateSchema,
    LineUpdateSchema,
    OrderCreateSchema,
    OrderUpdateSchema,
    ProductCreateSchema,
    TagCreateSchema,
)
from core.tests.computed_app.services import (
    LineService,
    OrderService,
    ProductService,
    TagService,
)


def updates_of(queries, model):
    """The UPDATE statements a block ran on `model`'s table."""
    table = model._meta.db_table
    return [q["sql"] for q in queries if q["sql"].startswith(f'UPDATE "{table}"')]


class ComputedServiceTestCase(TestCase):

    def setUp(self):
        self.env = Environment(None)
        self.orders = self.env.get(OrderService)
        self.lines = self.env.get(LineService)
        self.tags = self.env.get(TagService)
        self.products = self.env.get(ProductService)

    def create_tags(self, *names):
        return async_to_sync(self.tags.create)([TagCreateSchema(name=name) for name in names])

    def create_order(self, label="o", tags=()):
        (order,) = async_to_sync(self.orders.create)(
            [OrderCreateSchema(label=label, tags=[t.pk for t in tags])]
        )
        return order

    def create_lines(self, order, *specs):
        """`(quantity, unit_price[, product])` tuples."""
        return async_to_sync(self.lines.create)([
            LineCreateSchema(
                order=order.pk, quantity=spec[0], unit_price=Decimal(spec[1]),
                product=spec[2].pk if len(spec) > 2 else None,
            )
            for spec in specs
        ])

    def update(self, service, schema, pk, **values):
        return async_to_sync(service.update)({"pk": pk}, schema(**values))

    def delete(self, service, pk):
        return async_to_sync(service.delete)({"pk": pk})

    def fetch(self, model, pk):
        return model.objects.get(pk=pk)


class TestCreate(ComputedServiceTestCase):

    def test_created_instance_is_primed(self):
        """The controller serializes it as is: every computed value must be there,
        stored ones read back, virtual ones computed -- and no query left to run."""
        red, blue = self.create_tags("red", "blue")
        order = self.create_order("first", tags=[red, blue])
        with self.assertNumQueries(0):
            self.assertEqual(order.label_upper, "FIRST")
            self.assertEqual(order.tag_count, 2)
            self.assertEqual(order.tag_names, "blue, red")
            self.assertEqual(order.line_count, 0)
            self.assertEqual(order.line_count_virtual, 0)
            self.assertIsNone(order.max_quantity_virtual)

    def test_many_to_many_declared_on_the_other_side(self):
        (red,) = self.create_tags("red")
        self.create_order(tags=[red])
        self.assertEqual(self.fetch(Tag, red.pk).order_count, 1)

    def test_created_lines_refresh_their_order(self):
        order = self.create_order()
        first, _ = self.create_lines(order, (2, "1.5"), (1, "10"))
        self.assertEqual(first.amount, Decimal("3.00"))
        self.assertEqual(first.order_status, "draft")
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.line_count, 2)
        self.assertEqual(order.total, Decimal("13.00"))
        self.assertEqual(order.total_of_amounts, Decimal("13.00"))

    def test_one_update_per_model_and_depth(self):
        order = self.create_order()
        with CaptureQueriesContext(connection) as queries:
            self.create_lines(order, (1, "1"), (2, "1"), (3, "1"))
        # `Line.order_status` for the lines, then every field of the order reading
        # them in one statement. `Line.amount` is a generated column, computed by
        # the INSERT itself: `total_of_amounts` can read it at depth 0.
        self.assertEqual(len(updates_of(queries, Line)), 1)
        self.assertEqual(len(updates_of(queries, Order)), 1)

    def test_chain_is_refreshed_in_order(self):
        """`Order.tag_popularity` reads `Tag.order_count`: refreshed after it."""
        (red,) = self.create_tags("red")
        self.create_order("first", tags=[red])
        second = self.create_order("second", tags=[red])
        self.assertEqual(self.fetch(Order, second.pk).tag_popularity, 2)

    def test_failed_creation_refreshes_nothing(self):
        order = self.create_order()
        with self.assertRaises(ServiceValidationMultiError):
            async_to_sync(self.lines.create)([
                LineCreateSchema(order=order.pk, quantity=1, unit_price=Decimal("1")),
                LineCreateSchema(order="unknown", quantity=1, unit_price=Decimal("1")),
            ])
        self.assertEqual(self.fetch(Order, order.pk).line_count, 0)


class TestUpdate(ComputedServiceTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.create_order()
        self.line, _ = self.create_lines(self.order, (2, "1"), (1, "1"))

    def test_value(self):
        with CaptureQueriesContext(connection) as queries:
            self.update(self.lines, LineUpdateSchema, self.line.pk, quantity=5)
        order = self.fetch(Order, self.order.pk)
        self.assertEqual(order.total, Decimal("6.00"))
        self.assertEqual(order.total_of_amounts, Decimal("6.00"))
        self.assertEqual(self.fetch(Line, self.line.pk).amount, Decimal("5.00"))
        # the write itself (postgres recomputes `amount` in it), then one statement
        # for every field of the order reading the line
        self.assertEqual(len(updates_of(queries, Line)), 1)
        self.assertEqual(len(updates_of(queries, Order)), 1)

    def test_unwatched_field_refreshes_nothing(self):
        (product,) = async_to_sync(self.products.create)([ProductCreateSchema(name="p")])
        with CaptureQueriesContext(connection) as queries:
            self.update(self.lines, LineUpdateSchema, self.line.pk, product=product.pk)
        self.assertEqual(len(updates_of(queries, Line)), 1)  # the write itself
        self.assertEqual(updates_of(queries, Order), [])

    def test_foreign_key_reassignment(self):
        other = self.create_order("other")
        self.update(self.lines, LineUpdateSchema, self.line.pk, order=other.pk)
        self.assertEqual(self.fetch(Order, self.order.pk).line_count, 1)
        self.assertEqual(self.fetch(Order, other.pk).line_count, 1)
        self.assertEqual(self.fetch(Order, other.pk).total, Decimal("2.00"))

    def test_local_field_costs_no_refresh(self):
        """`label_upper` is a generated column: the write is the only UPDATE."""
        with CaptureQueriesContext(connection) as queries:
            self.update(self.orders, OrderUpdateSchema, self.order.pk, label="renamed")
        self.assertEqual(self.fetch(Order, self.order.pk).label_upper, "RENAMED")
        self.assertEqual(len(updates_of(queries, Order)), 1)

    def test_forward_foreign_key_field(self):
        self.update(self.orders, OrderUpdateSchema, self.order.pk, status="sent")
        self.assertEqual(self.fetch(Line, self.line.pk).order_status, "sent")

    def test_many_to_many_both_sides(self):
        red, blue = self.create_tags("red", "blue")
        self.update(self.orders, OrderUpdateSchema, self.order.pk, tags=[red.pk])
        self.assertEqual(self.fetch(Tag, red.pk).order_count, 1)

        self.update(self.orders, OrderUpdateSchema, self.order.pk, tags=[blue.pk])
        order = self.fetch(Order, self.order.pk)
        self.assertEqual((order.tag_count, order.tag_names), (1, "blue"))
        # the tag leaving the relation is found before the write
        self.assertEqual(self.fetch(Tag, red.pk).order_count, 0)
        self.assertEqual(self.fetch(Tag, blue.pk).order_count, 1)

    def test_field_of_a_many_to_many(self):
        (red,) = self.create_tags("red")
        self.update(self.orders, OrderUpdateSchema, self.order.pk, tags=[red.pk])
        async_to_sync(self.tags.update)({"pk": red.pk}, self.tags.update_schema(name="crimson"))
        self.assertEqual(self.fetch(Order, self.order.pk).tag_names, "crimson")


class TestDelete(ComputedServiceTestCase):

    def test_line(self):
        order = self.create_order()
        line, _ = self.create_lines(order, (1, "1"), (1, "1"))
        self.delete(self.lines, line.pk)
        self.assertEqual(self.fetch(Order, order.pk).line_count, 1)

    def test_cascade(self):
        order = self.create_order()
        (product,) = async_to_sync(self.products.create)([ProductCreateSchema(name="p")])
        self.create_lines(order, (1, "1", product), (1, "1"))
        self.delete(self.products, product.pk)  # cascades to one line
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.line_count, 1)
        self.assertEqual(order.total, Decimal("1.00"))

    def test_root_of_a_many_to_many(self):
        (red,) = self.create_tags("red")
        order = self.create_order(tags=[red])
        self.delete(self.orders, order.pk)
        self.assertEqual(self.fetch(Tag, red.pk).order_count, 0)

    def test_tag(self):
        red, blue = self.create_tags("red", "blue")
        order = self.create_order(tags=[red, blue])
        self.delete(self.tags, red.pk)
        order = self.fetch(Order, order.pk)
        self.assertEqual((order.tag_count, order.tag_names), (1, "blue"))


class TestUnitOfWork(ComputedServiceTestCase):

    def test_derived_environments_share_the_context(self):
        derived = self.orders.with_context(dry_run=True).env
        self.assertIsNot(derived, self.env)
        self.assertIs(derived.computed_refresh(), self.env.computed_refresh())

    def test_separate_environments_do_not(self):
        self.assertIsNot(Environment(None).computed_refresh(), self.env.computed_refresh())

    def test_nested_writes_flush_once_at_the_outermost_exit(self):
        order = self.create_order()
        with self.env.computed_refresh():
            lines = self.create_lines(order, (1, "1"), (1, "1"))
            # not flushed yet: the outer unit of work is still open...
            self.assertEqual(self.fetch(Order, order.pk).line_count, 0)
            # ... so what the nested write returns is primed with pre-flush values
            self.assertIsNone(lines[0].order_status)
            # -- except generated columns, returned by the INSERT itself
            self.assertEqual(lines[0].amount, Decimal("1.00"))
        self.assertEqual(self.fetch(Order, order.pk).line_count, 2)


class TestRead(ComputedServiceTestCase):

    def setUp(self):
        super().setUp()
        self.order = self.create_order()
        self.create_lines(self.order, (2, "1"), (7, "1"))

    def test_virtual_fields_are_loaded_for_an_async_consumer(self):
        """Read from a coroutine, as ninja serializes: the descriptor's fallback
        would raise `SynchronousOnlyOperation` if anything were left unloaded."""

        async def consume():
            queryset = await self.orders.read(
                fields=["id", "line_count", "line_count_virtual", "max_quantity_virtual"]
            )
            return [
                (o.line_count, o.line_count_virtual, o.max_quantity_virtual)
                async for o in queryset
            ]

        self.assertEqual(async_to_sync(consume)(), [(2, 2, 7)])

    def test_apply_query_fields_leaves_columns_to_queryset_fetch_fields(self):
        queryset = self.orders.apply_query_fields(Order.objects.all(), ["id", "total", "line_count_virtual"])
        self.assertEqual(queryset.query.deferred_loading, ({"id", "total"}, False))
        self.assertIn("line_count_virtual", queryset.query.annotations)
