from django.test import TestCase
from parameterized import parameterized

from core.orm.queryset import queryset_fetch_fields
from core.tests.computed_app.models import Line, Order, Product


class TestQuerysetFetchFields(TestCase):

    @classmethod
    def setUpTestData(cls):
        product = Product.objects.create(name="Pipe")
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
