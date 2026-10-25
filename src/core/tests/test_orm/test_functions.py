from decimal import Decimal

from django.db.models import FloatField, Sum
from django.db.models.functions import Cast
from django.test import TestCase

from core.orm.functions import SumOverGroups
from core.tests.computed_app.models import Category, Line, Order, Product


class TestSumOverGroups(TestCase):
    """`SumOverGroups` relies on django internals: these tests are what tells an
    upgrade broke them."""

    @classmethod
    def setUpTestData(cls):
        cls.hammer, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=Category.objects.create(name="Tools")),
            Product(name="Bread"),
        ])
        cls.first, cls.second = Order.objects.bulk_create([Order(label="first"), Order(label="second")])
        Line.objects.bulk_create([
            Line(order=cls.first, product=cls.hammer, quantity=1),
            Line(order=cls.first, product=cls.hammer, quantity=2),
            Line(order=cls.first, product=cls.bread, quantity=3),
            Line(order=cls.second, product=cls.bread, quantity=4),
        ])

    def group(self, *keys, exclude=()):
        rows = (
            Line.objects.order_by().values(*keys)
            .annotate(quantity_sum=Sum("quantity"), total=SumOverGroups("quantity", exclude=exclude))
            .order_by(*keys)
        )
        return [tuple(row[key] for key in (*keys, "quantity_sum", "total")) for row in rows]

    def test_partition_is_the_group_keys_but_excluded(self):
        # The total of each order, whatever the product.
        self.assertEqual(
            self.group("order", "product", exclude=["product"]),
            [
                (self.first.pk, self.hammer.pk, 3, 6),
                (self.first.pk, self.bread.pk, 3, 6),
                (self.second.pk, self.bread.pk, 4, 4),
            ],
        )

    def test_every_key_excluded_is_the_grand_total(self):
        self.assertEqual(
            self.group("order", exclude=["order"]),
            [(self.first.pk, 6, 10), (self.second.pk, 4, 10)],
        )

    def test_no_key_excluded_is_the_group_itself(self):
        self.assertEqual(self.group("order"), [(self.first.pk, 6, 6), (self.second.pk, 4, 4)])

    def test_partition_follows_annotations(self):
        # A non-aggregate annotation grouped by -- the date truncations of a group by
        # -- partitions like a `values()` field.
        rows = (
            Line.objects.order_by().annotate(big=Cast("quantity", FloatField())).values("order", "big")
            .annotate(total=SumOverGroups("quantity", exclude=["big"]))
            .order_by("order", "big")
        )
        self.assertEqual([row["total"] for row in rows], [6, 6, 6, 4])

    def test_not_in_group_by(self):
        queryset = (
            Line.objects.order_by().values("order")
            .annotate(share=Cast(Sum("quantity"), FloatField()) / SumOverGroups("quantity", exclude=["order"]))
        )
        sql = str(queryset.query)

        self.assertEqual(sql.count("GROUP BY"), 1)
        self.assertNotIn("OVER", sql.split("GROUP BY")[1])
        self.assertEqual(
            sorted(row["share"] for row in queryset), [0.4, 0.6],
        )

    def test_a_declaration_serves_every_query(self):
        # Declared once on a service class: resolving it for one query must not
        # leave that query's partition on it for the next.
        expression = SumOverGroups("quantity")
        by_order = Line.objects.order_by().values("order").annotate(total=expression)
        by_product = Line.objects.order_by().values("product").annotate(total=expression)

        self.assertEqual(sorted(row["total"] for row in by_order), [4, 6])
        self.assertEqual(sorted(row["total"] for row in by_product), [3, 7])
        self.assertIsNone(expression.partition_by)

    def test_decimal(self):
        Line.objects.update(unit_price=Decimal("2.50"))
        rows = Line.objects.order_by().values("order").annotate(total=SumOverGroups("unit_price", exclude=["order"]))

        self.assertEqual({row["total"] for row in rows}, {Decimal("10.00")})
