from django.test import TestCase
from parameterized import parameterized

from core.orm.queryset import model_instance_to_dict, queryset_fetch_fields
from core.tests.computed_app.models import Category, Line, Order, Product


class TestQuerysetFetchFields(TestCase):

    @classmethod
    def setUpTestData(cls):
        product = Product.objects.create(name="Pipe", category=Category.objects.create(name="Smoking"))
        for label in ("A", "B", "C"):
            order = Order.objects.create(label=label)
            Line.objects.create(order=order, product=product)

    @parameterized.expand(
        [
            # The rows, then one prefetch per relation: never one query per row.
            ("fields of the relation", ["id", "order__id", "order__label"], 2),
            ("two relations", ["id", "order__label", "product__name"], 3),
            # Not prefetched: read as its bare pk, from the column of the row.
            ("bare foreign key", ["id", "order"], 1),
        ]
    )
    def test_foreign_key_column_is_not_deferred(self, dummy, lookups, query_count):
        queryset = queryset_fetch_fields(Line.objects.all(), lookups)

        with self.assertNumQueries(query_count):
            lines = list(queryset)
            for line in lines:
                if "order" in lookups:
                    line.order_id
                else:
                    line.order.label
        self.assertEqual(len(lines), 3)

    def test_foreign_key_column_is_loaded(self):
        queryset = queryset_fetch_fields(Line.objects.all(), ["id", "order__label"])

        self.assertEqual(queryset.query.deferred_loading, ({"id", "order"}, False))

    def test_nested_relation_is_prefetched(self):
        """A relation of a relation: one prefetch per level, nested in the one
        above. The nested `Prefetch` used to be read as a dict, so any schema
        reaching that deep failed to build its queryset."""
        queryset = queryset_fetch_fields(Line.objects.all(), ["id", "product__name", "product__category__name"])

        with self.assertNumQueries(3):
            names = [line.product.category.name for line in queryset]
        self.assertEqual(names, ["Smoking"] * 3)


class TestModelInstanceToDict(TestCase):
    """What a list route serializes: see `PageNumberPagination`."""

    @classmethod
    def setUpTestData(cls):
        product = Product.objects.create(name="Pipe", category=Category.objects.create(name="Smoking"))
        cls.order = Order.objects.create(label="A")
        Line.objects.create(order=cls.order, product=product)

    def test_reverse_relation_leaves_out_its_back_reference(self):
        """A prefetched reverse foreign key caches the order on each line too: it
        used to be followed back, line to order to line, until a RecursionError.
        A one-to-one does the same, from either side (see `payment`)."""
        [order] = queryset_fetch_fields(Order.objects.all(), ["id", "lines__id", "lines__product__name"])

        values = model_instance_to_dict(order)

        [line] = values["lines"]
        self.assertNotIn("order", line)
        self.assertEqual(line["product"]["name"], "Pipe")

    def test_forward_relation_is_kept(self):
        [line] = queryset_fetch_fields(Line.objects.all(), ["id", "order__label", "product__category__name"])

        values = model_instance_to_dict(line)

        self.assertEqual(values["order"]["label"], "A")
        self.assertEqual(values["product"]["category"]["name"], "Smoking")
