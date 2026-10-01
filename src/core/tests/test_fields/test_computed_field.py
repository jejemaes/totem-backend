import types
from decimal import Decimal

from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import models
from django.db.models import Count, F, OuterRef, Subquery, Sum, Value, Window
from django.db.models.functions import Upper
from django.test import SimpleTestCase, TestCase
from django.test.utils import isolate_apps

from core.orm.fields import ComputedField, ComputedQuerySetMixin
from core.orm.fields.computed import (
    RefreshComputedFieldsContext,
    computed_fields_to_refresh,
    get_computed_field,
    prime_computed_values,
)
from core.orm.fields.computed.dependency import _parse_dependency, get_registry
from core.orm.fields.computed.field import is_row_local
from core.orm.fields.computed.utils import as_subquery
from core.tests.computed_app.models import Line, Order, Product, Tag


class TestRegistries(SimpleTestCase):

    def test_four_registries(self):
        meta = Order._meta
        self.assertEqual(
            set(meta.stored_computed_fields),
            {"line_count", "total", "total_of_amounts", "tag_count", "tag_popularity", "tag_names"},
        )
        self.assertEqual(set(meta.virtual_computed_fields), {"line_count_virtual", "max_quantity_virtual"})
        self.assertEqual(
            set(meta.computed_annotation_fields),
            {"line_count", "total", "total_of_amounts", "tag_count", "tag_popularity", "line_count_virtual"},
        )
        self.assertEqual(set(meta.computed_prefetch_fields), {"tag_names", "max_quantity_virtual"})

    def test_each_field_sits_in_exactly_two_registries(self):
        meta = Order._meta
        registries = (
            meta.stored_computed_fields, meta.virtual_computed_fields,
            meta.computed_annotation_fields, meta.computed_prefetch_fields,
        )
        names = set().union(*registries)
        for name in names:
            self.assertEqual(sum(name in registry for registry in registries), 2, name)

    def test_a_model_without_computed_field_has_no_registry(self):
        self.assertFalse(hasattr(Product._meta, "stored_computed_fields"))
        self.assertIsNone(get_computed_field(Product, "name"))

    def test_stored_field_is_a_concrete_field(self):
        concrete = {f.name for f in Order._meta.concrete_fields}
        self.assertTrue(set(Order._meta.stored_computed_fields) <= concrete)
        self.assertIs(Order._meta.get_field("total"), Order._meta.stored_computed_fields["total"])

    def test_virtual_field_is_invisible_to_django(self):
        everything = {f.name for f in Order._meta.get_fields()}
        for name in Order._meta.virtual_computed_fields:
            self.assertNotIn(name, everything)

    def test_deconstruct(self):
        name, path, args, kwargs = Order._meta.get_field("total").deconstruct()
        self.assertEqual(path, "core.orm.fields.ComputedField")
        self.assertTrue(kwargs["stored"])
        self.assertIsInstance(kwargs["output_field"], models.DecimalField)
        for behaviour in ("annotation_method", "prefetch_method", "depends_on"):
            self.assertNotIn(behaviour, kwargs)

    def test_migration_replay_without_behaviour(self):
        """What a migration rebuilds from `deconstruct()` must construct."""
        ComputedField(output_field=models.IntegerField(), stored=True, null=True, editable=False)


class TestGeneratedField(SimpleTestCase):
    """A stored field reading only its own row is handed to PostgreSQL."""

    def test_row_local_stored_field_becomes_a_generated_field(self):
        for model, name in ((Order, "label_upper"), (Line, "amount")):
            with self.subTest(field=f"{model.__name__}.{name}"):
                field = model._meta.get_field(name)
                self.assertIsInstance(field, models.GeneratedField)
                self.assertNotIsInstance(field, ComputedField)
                self.assertTrue(field.db_persist)
                self.assertTrue(field.null)
                self.assertIsNone(get_computed_field(model, name))  # in no registry

    def test_what_stays_a_computed_field(self):
        local = lambda: Upper("label")  # noqa: E731
        cases = {
            "an aggregate": dict(annotation_method=lambda: Count("lines"), stored=True),
            "a relation": dict(annotation_method=lambda: F("order__status"), stored=True),
            "a subquery": dict(annotation_method=lambda: Subquery(Order.objects.values("label")[:1]), stored=True),
            "a prefetch method": dict(prefetch_method="p", stored=True),
            "a virtual field": dict(annotation_method=local),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                field = ComputedField(output_field=models.CharField(max_length=8), **kwargs)
                self.assertIsInstance(field, ComputedField)

    def test_is_row_local(self):
        self.assertTrue(is_row_local(F("quantity") * F("unit_price")))
        self.assertTrue(is_row_local(Upper("label")))
        self.assertTrue(is_row_local(Value(1)))
        self.assertFalse(is_row_local(Sum("quantity")))
        self.assertFalse(is_row_local(Upper("order__label")))
        self.assertFalse(is_row_local(Window(Count("id"))))

    def test_dependents_watch_the_inputs(self):
        """Nobody writes `Line.amount`: postgres recomputes it when `quantity` or
        `unit_price` are. A field depending on it reacts to those."""
        (binding,) = _parse_dependency(Order, Order._meta.get_field("total_of_amounts"), "lines__amount")
        self.assertTrue({"amount", "quantity", "unit_price"} <= binding.trigger_fields)
        self.assertEqual(binding.membership_fields, {"order", "order_id"})


class TestDeclarationErrors(SimpleTestCase):

    def test_virtual_needs_exactly_one_method(self):
        with self.assertRaises(ImproperlyConfigured):
            ComputedField(output_field=models.IntegerField())
        with self.assertRaises(ImproperlyConfigured):
            ComputedField(
                output_field=models.IntegerField(),
                annotation_method=lambda: Count("x"), prefetch_method="p",
            )

    def test_virtual_needs_output_field(self):
        with self.assertRaises(ImproperlyConfigured):
            ComputedField(annotation_method=lambda: Count("x"))

    @isolate_apps("core.tests.computed_app")
    def test_virtual_refused_on_abstract_model(self):
        with self.assertRaises(ImproperlyConfigured):
            class Base(models.Model):
                count = ComputedField(output_field=models.IntegerField(), annotation_method=lambda: Count("x"))

                class Meta:
                    abstract = True

    @isolate_apps("core.tests.computed_app")
    def test_checks(self):
        class Plain(models.Model):
            # no ComputedQuerySetMixin, no method, no depends_on
            value = ComputedField(output_field=models.IntegerField(), stored=True)

        ids = {error.id for error in Plain._meta.get_field("value").check_computed()}
        self.assertEqual(ids, {"computed_field.E002", "computed_field.E003", "computed_field.E004"})

    @isolate_apps("core.tests.computed_app")
    def test_checks_pass_on_a_well_formed_field(self):
        class WellFormedQuerySet(ComputedQuerySetMixin, models.QuerySet):
            pass

        class WellFormed(models.Model):
            label = models.CharField(max_length=8)
            value = ComputedField(
                output_field=models.IntegerField(), annotation_method=lambda: Count("pk"),
                depends_on=["label"], stored=True,
            )
            objects = WellFormedQuerySet.as_manager()

        self.assertEqual(WellFormed._meta.get_field("value").check_computed(), [])


class TestDependencyParsing(SimpleTestCase):

    def _bindings(self, model, name, dep):
        return list(_parse_dependency(model, model._meta.get_field(name), dep))

    def test_local(self):
        (binding,) = self._bindings(Order, "total", "label")
        self.assertTrue(binding.is_local)
        self.assertEqual(binding.trigger_fields, {"label"})

    def test_reverse_foreign_key(self):
        (binding,) = self._bindings(Order, "total", "lines__quantity")
        self.assertIs(binding.watched_model, Line)
        self.assertEqual(binding.path, "lines")
        self.assertEqual(binding.fk_attname, "order_id")
        # reassigning the key moves the line to another order
        self.assertEqual(binding.membership_fields, {"order", "order_id"})
        self.assertEqual(binding.trigger_fields, {"order", "order_id", "quantity"})

    def test_forward_foreign_key(self):
        local, remote = self._bindings(Line, "order_status", "order__status")
        self.assertTrue(local.is_local)
        self.assertEqual(local.trigger_fields, {"order", "order_id"})
        self.assertIs(remote.watched_model, Order)
        self.assertEqual(remote.path, "order")
        self.assertEqual(remote.trigger_fields, {"status"})

    def test_many_to_many_declared_here(self):
        local, remote = self._bindings(Order, "tag_names", "tags__name")
        self.assertEqual(local.trigger_fields, {"tags"})
        self.assertIs(remote.watched_model, Tag)
        self.assertEqual(remote.trigger_fields, {"name"})

    def test_many_to_many_declared_on_the_other_side(self):
        (binding,) = self._bindings(Tag, "order_count", "orders")
        self.assertIs(binding.watched_model, Order)
        self.assertEqual(binding.trigger_fields, {"tags"})
        self.assertEqual(binding.membership_fields, {"tags"})

    def test_refused_shapes(self):
        field = Order._meta.get_field("total")
        for dep in ("lines__order__status", "nope", "label__x", "lines__nope"):
            with self.subTest(dep=dep), self.assertRaises(ImproperlyConfigured):
                list(_parse_dependency(Order, field, dep))

    def test_reverse_relation_as_second_hop_refused(self):
        field = Line._meta.get_field("order_status")
        with self.assertRaises(ImproperlyConfigured):
            list(_parse_dependency(Line, field, "order__lines"))

    def test_depth_orders_chains(self):
        depth = get_registry().depth
        self.assertLess(depth[Tag._meta.get_field("order_count")], depth[Order._meta.get_field("tag_popularity")])
        # A generated field is no step of a chain: it is current before any flush.
        self.assertEqual(depth[Order._meta.get_field("total_of_amounts")], 0)

    def test_cascades(self):
        cascades = get_registry().cascades
        self.assertIn(Line, cascades[Product])
        self.assertNotIn(Tag, cascades)  # deleting a tag reaches no watched row through on_delete


class ComputedTestCase(TestCase):

    def create_orders(self, *labels):
        orders = Order.objects.bulk_create([Order(label=label) for label in labels])
        with RefreshComputedFieldsContext() as ctx:
            ctx.created(orders)
        return orders

    def create_lines(self, *specs):
        """`(order, quantity, unit_price[, product])` tuples."""
        lines = Line.objects.bulk_create([
            Line(order=spec[0], quantity=spec[1], unit_price=Decimal(spec[2]),
                 product=spec[3] if len(spec) > 3 else None)
            for spec in specs
        ])
        with RefreshComputedFieldsContext() as ctx:
            ctx.created(lines)
        return lines

    def fetch(self, model, pk):
        return model.objects.get(pk=pk)


class TestContext(ComputedTestCase):

    def test_created_rows_get_their_own_values(self):
        (order,) = self.create_orders("first")
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.label_upper, "FIRST")
        self.assertEqual(order.line_count, 0)
        self.assertEqual(order.total, Decimal("0"))
        self.assertEqual(order.tag_names, "")

    def test_created_lines_refresh_their_order(self):
        (order,) = self.create_orders("o")
        line, _ = self.create_lines((order, 2, "1.50"), (order, 1, "10"))
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.line_count, 2)
        self.assertEqual(order.total, Decimal("13.00"))
        # a chain: Line.amount is refreshed before the total reading it
        self.assertEqual(order.total_of_amounts, Decimal("13.00"))
        line = self.fetch(Line, line.pk)
        self.assertEqual(line.amount, Decimal("3.00"))
        self.assertEqual(line.order_status, "draft")

    def test_value_update(self):
        (order,) = self.create_orders("o")
        line, _ = self.create_lines((order, 2, "1"), (order, 1, "1"))
        Line.objects.filter(pk=line.pk).update(quantity=5)
        # the orders of the line, resolved once for `total` and `total_of_amounts`,
        # then one UPDATE setting both -- `Line.amount` was already recomputed by
        # postgres in the write, and `line_count` is untouched
        with self.assertNumQueries(2):
            with RefreshComputedFieldsContext() as ctx:
                ctx.modified(Line, [line.pk], {"quantity"})
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.total, Decimal("6.00"))
        self.assertEqual(order.total_of_amounts, Decimal("6.00"))

    def test_unwatched_field_costs_nothing(self):
        (order,) = self.create_orders("o")
        (line,) = self.create_lines((order, 1, "1"))
        (product,) = Product.objects.bulk_create([Product(name="p")])
        Line.objects.filter(pk=line.pk).update(product=product)
        with self.assertNumQueries(0):  # no computed field depends on `lines__product`
            with RefreshComputedFieldsContext() as ctx:
                ctx.modified(Line, [line.pk], {"product"})

    def test_foreign_key_reassignment_refreshes_both_roots(self):
        first, second = self.create_orders("a", "b")
        line, _ = self.create_lines((first, 1, "1"), (first, 1, "1"))
        with RefreshComputedFieldsContext() as ctx:
            self.assertTrue(ctx.has_relation_to_modify(Line, {"order"}))
            ctx.modified(Line, [line.pk], {"order"}, before=True)
            Line.objects.filter(pk=line.pk).update(order=second)
            ctx.modified(Line, [line.pk], {"order"})
        self.assertEqual(self.fetch(Order, first.pk).line_count, 1)
        self.assertEqual(self.fetch(Order, second.pk).line_count, 1)

    def test_forward_foreign_key_field(self):
        (order,) = self.create_orders("o")
        (line,) = self.create_lines((order, 1, "1"))
        Order.objects.filter(pk=order.pk).update(status="sent")
        with RefreshComputedFieldsContext() as ctx:
            ctx.modified(Order, [order.pk], {"status"})
        self.assertEqual(self.fetch(Line, line.pk).order_status, "sent")

    def test_many_to_many(self):
        (order,) = self.create_orders("o")
        red, blue = Tag.objects.bulk_create([Tag(name="red"), Tag(name="blue")])
        with RefreshComputedFieldsContext() as ctx:
            ctx.created([red, blue])
        with RefreshComputedFieldsContext() as ctx:
            ctx.modified(Order, [order.pk], {"tags"}, before=True)
            order.tags.set([red, blue])
            ctx.modified(Order, [order.pk], {"tags"})
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.tag_count, 2)
        self.assertEqual(order.tag_names, "blue, red")
        self.assertEqual(self.fetch(Tag, red.pk).order_count, 1)

        with RefreshComputedFieldsContext() as ctx:
            ctx.modified(Order, [order.pk], {"tags"}, before=True)
            order.tags.set([blue])
            ctx.modified(Order, [order.pk], {"tags"})
        # the tag leaving the relation is refreshed too: captured before the write
        self.assertEqual(self.fetch(Tag, red.pk).order_count, 0)

        Tag.objects.filter(pk=blue.pk).update(name="navy")
        with RefreshComputedFieldsContext() as ctx:
            ctx.modified(Tag, [blue.pk], {"name"})
        self.assertEqual(self.fetch(Order, order.pk).tag_names, "navy")

    def test_deleted(self):
        (order,) = self.create_orders("o")
        line, _ = self.create_lines((order, 1, "1"), (order, 1, "1"))
        with RefreshComputedFieldsContext() as ctx:
            queryset = Line.objects.filter(pk=line.pk)
            ctx.deleted(queryset)
            queryset.delete()
        self.assertEqual(self.fetch(Order, order.pk).line_count, 1)

    def test_deleted_tag_leaves_the_relation(self):
        (order,) = self.create_orders("o")
        (tag,) = Tag.objects.bulk_create([Tag(name="red")])
        order.tags.set([tag])
        Order.objects.filter(pk=order.pk).refresh_computed()
        with RefreshComputedFieldsContext() as ctx:
            queryset = Tag.objects.filter(pk=tag.pk)
            ctx.deleted(queryset)
            queryset.delete()
        order = self.fetch(Order, order.pk)
        self.assertEqual(order.tag_count, 0)
        self.assertEqual(order.tag_names, "")

    def test_cascade(self):
        (order,) = self.create_orders("o")
        (product,) = Product.objects.bulk_create([Product(name="p")])
        self.create_lines((order, 1, "1", product), (order, 1, "1"))
        with RefreshComputedFieldsContext() as ctx:
            queryset = Product.objects.filter(pk=product.pk)
            ctx.deleted(queryset)
            queryset.delete()  # cascades to one line
        self.assertEqual(self.fetch(Order, order.pk).line_count, 1)

    def test_nesting_flushes_once_at_the_outermost_exit(self):
        (order,) = self.create_orders("o")
        (line,) = self.create_lines((order, 1, "1"))
        Order.objects.filter(pk=order.pk).update(status="sent")
        ctx = RefreshComputedFieldsContext()
        with ctx:
            with ctx:
                ctx.modified(Order, [order.pk], {"status"})
            self.assertEqual(self.fetch(Line, line.pk).order_status, "draft")
        self.assertEqual(self.fetch(Line, line.pk).order_status, "sent")

    def test_exception_drops_the_pending_work(self):
        (order,) = self.create_orders("o")
        (line,) = self.create_lines((order, 1, "1"))
        Order.objects.filter(pk=order.pk).update(status="sent")
        ctx = RefreshComputedFieldsContext()
        with self.assertRaises(RuntimeError):
            with ctx:
                ctx.modified(Order, [order.pk], {"status"})
                raise RuntimeError
        self.assertEqual(self.fetch(Line, line.pk).order_status, "draft")
        with ctx:
            pass  # nothing left over
        self.assertEqual(self.fetch(Line, line.pk).order_status, "draft")


class TestQuerySetApi(ComputedTestCase):

    def setUp(self):
        (self.order,) = self.create_orders("o")
        self.create_lines((self.order, 2, "1"), (self.order, 7, "1"))

    def test_refresh_computed_repairs_and_propagates(self):
        (tag,) = Tag.objects.bulk_create([Tag(name="red")])
        self.order.tags.set([tag])  # around the context: both sides are stale
        Order.objects.filter(pk=self.order.pk).update(line_count=99)
        Order.objects.filter(pk=self.order.pk).refresh_computed("line_count")
        self.assertEqual(self.fetch(Order, self.order.pk).line_count, 2)
        # refreshing the tag's count refreshes what reads it
        Tag.objects.filter(pk=tag.pk).refresh_computed("order_count")
        self.assertEqual(self.fetch(Tag, tag.pk).order_count, 1)
        self.assertEqual(self.fetch(Order, self.order.pk).tag_popularity, 1)

    def test_refresh_computed_refuses_a_generated_field(self):
        with self.assertRaises(FieldError):
            Line.objects.all().refresh_computed("amount")

    def test_refresh_computed_refuses_a_virtual_field(self):
        with self.assertRaises(FieldError):
            Order.objects.all().refresh_computed("line_count_virtual")

    def test_with_computed_annotation(self):
        with self.assertNumQueries(1):
            order = Order.objects.with_computed_annotation("line_count_virtual").get(pk=self.order.pk)
            self.assertEqual(order.line_count_virtual, 2)

    def test_with_computed_prefetch(self):
        with self.assertNumQueries(2):
            (order,) = Order.objects.filter(pk=self.order.pk).with_computed_prefetch("max_quantity_virtual")
            self.assertEqual(order.max_quantity_virtual, 7)

    def test_with_computed_dispatches(self):
        queryset = Order.objects.with_computed("line_count", "line_count_virtual", "max_quantity_virtual")
        self.assertIn("line_count_virtual", queryset.query.annotations)
        self.assertNotIn("line_count", queryset.query.annotations)
        self.assertEqual(queryset._computed_prefetch, {"max_quantity_virtual"})
        self.assertEqual(queryset._clone()._computed_prefetch, {"max_quantity_virtual"})

    def test_queryset_api_refuses_wrong_names(self):
        with self.assertRaises(FieldError):
            Order.objects.with_computed_annotation("line_count")  # stored
        with self.assertRaises(FieldError):
            Order.objects.with_computed_prefetch("line_count_virtual")  # annotation
        with self.assertRaises(FieldError):
            Order.objects.with_computed("label")

    def test_descriptor_fallback(self):
        order = self.fetch(Order, self.order.pk)
        with self.assertNumQueries(2):
            self.assertEqual(order.line_count_virtual, 2)
            self.assertEqual(order.max_quantity_virtual, 7)
        with self.assertNumQueries(0):
            self.assertEqual(order.line_count_virtual, 2)

    def test_virtual_annotations_do_not_multiply(self):
        """Two computed values over two multi-valued relations, in one query: each is
        a correlated subquery, so neither multiplies the other's rows."""
        tags = Tag.objects.bulk_create([Tag(name="a"), Tag(name="b"), Tag(name="c")])
        self.order.tags.set(tags)
        order = (
            Order.objects
            .with_computed_annotation("line_count_virtual")
            .annotate(tags_n=as_subquery(Order._meta.get_field("tag_count")))
            .get(pk=self.order.pk)
        )
        self.assertEqual((order.line_count_virtual, order.tags_n), (2, 3))

    def test_prime_computed_values(self):
        order = Order(pk=self.order.pk)  # as built in memory, values unknown
        with self.assertNumQueries(2):  # stored + annotated together, then the prefetch
            prime_computed_values([order])
        with self.assertNumQueries(0):
            self.assertEqual(order.line_count, 2)
            self.assertEqual(order.line_count_virtual, 2)
            self.assertEqual(order.max_quantity_virtual, 7)
            self.assertEqual(order.tag_names, "")

    def test_computed_fields_to_refresh(self):
        line = Line.objects.filter(order=self.order).first()
        result = computed_fields_to_refresh(line, changed_fields={"quantity"})
        # `total_of_amounts` reads the generated `amount`, so it watches `quantity`
        self.assertEqual(result, {(Order, self.order.pk): {"total", "total_of_amounts"}})


class TestStoredEqualsVirtual(ComputedTestCase):
    """The same `annotation_method` gives the same value as a column (through the
    UPDATE) and as an annotation (through the SELECT), whatever its shape."""

    def test_every_stored_annotation_field(self):
        (order,) = self.create_orders("mixed")
        tags = Tag.objects.bulk_create([Tag(name="a"), Tag(name="b")])
        with RefreshComputedFieldsContext() as ctx:
            order.tags.set(tags)
            ctx.modified(Order, [order.pk], {"tags"})
        self.create_lines((order, 3, "2.5"), (order, 1, "4"))

        for model in (Order, Line, Tag):
            for field in model._meta.computed_annotation_fields.values():
                if not field.stored:
                    continue
                with self.subTest(field=f"{model.__name__}.{field.name}"):
                    for row in model.objects.annotate(as_select=as_subquery(field)):
                        self.assertEqual(getattr(row, field.name), row.as_select)

    def test_handwritten_subquery_is_accepted(self):
        (order,) = self.create_orders("o")
        self.create_lines((order, 1, "1"), (order, 1, "1"), (order, 1, "1"))
        per_order = (
            Line.objects.filter(order=OuterRef("pk")).order_by()
            .values("order").annotate(n=Count("pk")).values("n")
        )
        fake = types.SimpleNamespace(
            model=Order, name="handwritten", output_field=models.IntegerField(),
            get_annotation=lambda: Subquery(per_order),
        )
        Order.objects.filter(pk=order.pk).update(line_count=as_subquery(fake))
        self.assertEqual(self.fetch(Order, order.pk).line_count, 3)
