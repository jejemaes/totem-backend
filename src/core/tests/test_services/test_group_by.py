from decimal import Decimal
from unittest import mock

from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.test import TestCase
from parameterized import parameterized

from core.services import Dimension, Environment, GroupByMixin, Measure, ServiceValidationMultiError
from core.services.group_by import date_dimensions
from core.tests.computed_app.models import Category, Line, Order, Product, Tag
from core.tests.computed_app.services import LineService, ProductService


class TestGroupBy(TestCase):
    """`GroupByMixin.group_by`, on `LineService`."""

    @classmethod
    def setUpTestData(cls):
        cls.hammer, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=Category.objects.create(name="Tools")),
            Product(name="Bread"),
        ])
        cls.first, cls.second = Order.objects.bulk_create([
            Order(label="first", status="draft"), Order(label="second", status="done"),
        ])
        Line.objects.bulk_create([
            Line(order=cls.first, product=cls.hammer, quantity=1, unit_price=Decimal("10.00")),
            Line(order=cls.first, product=cls.hammer, quantity=2, unit_price=Decimal("10.00")),
            Line(order=cls.first, product=cls.bread, quantity=3, unit_price=Decimal("1.50")),
            Line(order=cls.second, product=cls.bread, quantity=4, unit_price=Decimal("1.50")),
            Line(order=cls.second, product=None, quantity=5, unit_price=Decimal("0.00")),
        ])

    def setUp(self):
        super().setUp()
        self.service = Environment(None).get(LineService)

    def group_by(self, *args, **kwargs):
        return async_to_sync(self.service.group_by)(*args, **kwargs)

    def test_group_by_measures(self):
        total, rows = self.group_by(["order"], ["count", "quantity_sum", "quantity_avg", "amount_sum"])

        self.assertEqual(total, 2)
        self.assertEqual(
            [(row["order"], row["count"], row["quantity_sum"], row["quantity_avg"], row["amount_sum"]) for row in rows],
            [
                (self.first, 3, 6, 2.0, Decimal("34.50")),
                (self.second, 2, 9, 4.5, Decimal("6.00")),
            ],
        )
        self.assertEqual(set(rows[0]), {"order", "count", "quantity_sum", "quantity_avg", "amount_sum"})

    def test_group_by_null_group(self):
        total, rows = self.group_by(["product"], ["quantity_sum"])

        self.assertEqual(total, 3)
        # Ordered by the column, NULLs last.
        self.assertEqual(
            [(row["product"], row["quantity_sum"]) for row in rows],
            [(self.hammer, 3), (self.bread, 7), (None, 5)],
        )

    def test_group_by_share(self):
        # The share of each product in its order: `exclude=["product"]`.
        total, rows = self.group_by(["order", "product"], ["quantity_share"])

        self.assertEqual(
            [(row["order"], row["product"], round(row["quantity_share"], 6)) for row in rows],
            [
                (self.first, self.hammer, 50.0),
                (self.first, self.bread, 50.0),
                (self.second, self.bread, round(4 / 9 * 100, 6)),
                (self.second, None, round(5 / 9 * 100, 6)),
            ],
        )

    def test_group_by_share_of_the_whole_page(self):
        # Computed before the limit: a share stays relative to every group.
        total, rows = self.group_by(["order", "product"], ["quantity_share"], ordering=["-quantity_share"], limit=1)

        self.assertEqual(total, 4)
        self.assertEqual([round(row["quantity_share"], 6) for row in rows], [round(5 / 9 * 100, 6)])

    @parameterized.expand(
        [
            ("by a measure", ["-quantity_sum"], lambda first, second: [second, first]),
            ("by a key", ["-order"], lambda first, second: sorted([first, second], key=lambda o: o.pk, reverse=True)),
            ("by default, the keys", None, lambda first, second: sorted([first, second], key=lambda o: o.pk)),
        ]
    )
    def test_group_by_ordering(self, dummy, ordering, expected):
        total, rows = self.group_by(["order"], ["quantity_sum"], ordering=ordering)

        self.assertEqual([row["order"] for row in rows], expected(self.first, self.second))

    def test_group_by_ordering_completed_by_the_keys(self):
        # Equal sums: the key not ordered on decides, so a page always holds the
        # same groups.
        Line.objects.filter(product=None).update(quantity=4)
        total, rows = self.group_by(["product"], ["quantity_max"], ordering=["-quantity_max"])

        self.assertEqual([row["product"] for row in rows], [self.bread, None, self.hammer])

    @parameterized.expand(
        [
            ("first page", 2, 0, [1, 2]),
            ("second page", 2, 2, [3, 4]),
            ("past the end", 2, 10, []),
            ("no limit", None, 0, [1, 2, 3, 4, 5]),
        ]
    )
    def test_group_by_pagination(self, dummy, limit, offset, quantities):
        total, rows = self.group_by(["quantity"], ["count"], limit=limit, offset=offset)

        self.assertEqual(total, 5)
        self.assertEqual([row["quantity"] for row in rows], quantities)

    def test_group_by_filters(self):
        total, rows = self.group_by(["order"], ["quantity_sum"], filters={"order__status": "done"})

        self.assertEqual((total, [row["order"] for row in rows]), (1, [self.second]))

    def test_group_by_access_rules(self):
        # A rule crossing a to-many relation: an order tagged twice joins twice. The
        # sums must not see it.
        tags = Tag.objects.bulk_create([Tag(name="a"), Tag(name="b")])
        self.first.tags.set(tags)

        async def apply_access_rules(service, queryset, operation):
            return queryset.filter(order__tags__name__in=["a", "b"])

        with mock.patch.object(LineService, "apply_access_rules", apply_access_rules):
            total, rows = self.group_by(["order"], ["count", "quantity_sum"])

        self.assertEqual([(row["order"], row["count"], row["quantity_sum"]) for row in rows], [(self.first, 3, 6)])

    def test_group_by_access_rules_of_a_relation(self):
        # A product the user may not read stays its bare pk.
        async def apply_access_rules(service, queryset, operation):
            return queryset.filter(name="Hammer")

        with mock.patch.object(ProductService, "apply_access_rules", apply_access_rules):
            total, rows = self.group_by(["product"], ["count"])

        self.assertEqual([row["product"] for row in rows], [self.hammer, self.bread.pk, None])

    def test_group_by_relation_fields(self):
        total, rows = self.group_by(["product"], ["count"], relation_fields={"product": ["id", "name"]})

        self.assertEqual(rows[0]["product"], self.hammer)
        self.assertEqual(rows[0]["product"].get_deferred_fields(), {"rank", "category_id"})

    def test_group_by_relation_fields_none(self):
        # Nothing to load: the pk stays, at no query.
        with self.assertNumQueries(2):
            total, rows = self.group_by(["product"], ["count"], relation_fields={"product": []})

        self.assertEqual([row["product"] for row in rows], [self.hammer.pk, self.bread.pk, None])

    @parameterized.expand(
        [
            ("no dimension", {"dimensions": []}, "dimensions", "At least one of"),
            ("unknown dimension", {"dimensions": ["unit_price"]}, "dimensions", "Unknown value(s): unit_price"),
            ("repeated dimension", {"dimensions": ["order", "order"]}, "dimensions", "Repeated value(s): order"),
            ("no measure", {"measures": []}, "measures", "At least one of"),
            ("unknown measure", {"measures": ["unit_price_sum"]}, "measures", "Unknown value(s): unit_price_sum"),
            ("ordering not asked", {"ordering": ["-amount_sum"]}, "ordering", "not grouped by nor measured: amount_sum"),
            ("ordering repeated", {"ordering": ["count", "-count"]}, "ordering", "Repeated value(s): count"),
            ("offset without limit", {"offset": 2}, "offset", "An offset requires a limit"),
        ]
    )
    def test_group_by_invalid(self, dummy, arguments, key, message):
        arguments = {"dimensions": ["order"], "measures": ["count"], **arguments}

        with self.assertNumQueries(0):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                self.group_by(**arguments)

        self.assertEqual(list(ctx.exception.dict()["__all__"]), [key])
        self.assertIn(message, ctx.exception.dict()["__all__"][key][0])

    def test_group_by_query_count(self):
        # The groups, their number, then one query per relation grouped by.
        with self.assertNumQueries(4):
            self.group_by(["order", "product"], ["count"])
        with self.assertNumQueries(2):
            self.group_by(["order_status"], ["count"])


class TestGroupByDeclarations(TestCase):
    """Checked when the service class is created: a typo fails at startup."""

    def declare(self, model=Line, dimensions=None, measures=None):
        # Not a `ServiceBase`: declaring one would register a second service of the
        # model. `GroupByMixin` only needs a `model`.
        return type(
            "StandInService", (GroupByMixin,),
            {"model": model, "group_by_dimensions": dimensions or {}, "group_by_measures": measures or {}},
        )

    def test_bound(self):
        service = self.declare(
            dimensions={"product": Dimension("product"), "qty": Dimension("quantity", label="Units")},
        )

        product, qty = service._group_by_dimensions["product"], service._group_by_dimensions["qty"]
        self.assertIs(product.related_model, Product)
        self.assertIsNone(product.expression)
        self.assertEqual(product.label, "Product")
        self.assertIsNone(qty.related_model)
        self.assertEqual(qty.label, "Units")
        self.assertIsInstance(qty.output_field, models.IntegerField)
        # Always there.
        self.assertEqual(list(service._group_by_measures), ["count"])

    def test_output_field_has_no_constraint(self):
        service = self.declare(measures={"price_max": Measure(models.Max("unit_price"), "unit_price")})

        output_field = service._group_by_measures["price_max"].output_field
        self.assertIsInstance(output_field, models.DecimalField)
        self.assertIsNone(output_field.max_digits)

    def test_date_dimensions(self):
        dimensions = date_dimensions("date", ["day", "month"])

        self.assertEqual(list(dimensions), ["date_day", "date_month"])
        self.assertEqual(dimensions["date_month"].truncate, "month")

    @parameterized.expand(
        [
            ("unknown field", {"dimensions": {"color": Dimension("color")}}, "no field of Line"),
            ("to-many", {"model": Order, "dimensions": {"tags": Dimension("tags")}}, "no column of Order"),
            ("reverse", {"model": Order, "dimensions": {"lines": Dimension("lines")}}, "no column of Order"),
            ("invalid name", {"dimensions": {"Order": Dimension("order")}}, "no valid name"),
            ("computed shadowing a field", {"dimensions": {"quantity": Dimension("unit_price")}}, "bears the name of a field"),
            ("truncating no date", {"dimensions": {"quantity_month": Dimension("quantity", truncate="month")}}, "which is none of []"),
            ("measure shadowing a field", {"measures": {"quantity": Measure(models.Sum("quantity"), "quantity")}}, "bears the name of a field"),
            ("measure without type", {"measures": {"total": Measure(models.Sum("quantity"))}}, "neither the field"),
            ("both", {"dimensions": {"count": Dimension("quantity")}}, "both a dimension and a measure"),
        ]
    )
    def test_invalid(self, dummy, declaration, message):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            self.declare(**declaration)

        self.assertIn(message, str(ctx.exception))

    def test_relation_without_service(self):
        from core.services.registry import ServiceRegistry

        service = self.declare(dimensions={"product": Dimension("product")})
        # Restored whole on exit, the deletion included.
        with mock.patch.dict(ServiceRegistry._by_model, {Line: service}):
            del ServiceRegistry._by_model[Product]
            with self.assertRaises(ImproperlyConfigured) as ctx:
                ServiceRegistry.validate()

        self.assertIn("the dimension 'product' groups by a relation to computed_app.Product", str(ctx.exception))
