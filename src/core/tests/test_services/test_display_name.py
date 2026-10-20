from asgiref.sync import async_to_sync
from django.db.models import Q
from django.test import TestCase
from parameterized import parameterized

from core.services import Environment
from core.tests.computed_app.models import Category, Product
from core.tests.computed_app.services import ProductService


class TestDisplayName(TestCase):
    """`ServiceBase.display_name`, on `ProductService`."""

    @classmethod
    def setUpTestData(cls):
        cls.tools, cls.food = Category.objects.bulk_create([Category(name="Tools"), Category(name="Food")])
        cls.hammer, cls.saw, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=cls.tools),
            Product(name="Saw", category=cls.tools),
            Product(name="Bread", category=cls.food),
        ])

    def setUp(self):
        super().setUp()
        self.service = Environment(None).get(ProductService)

    def display_name(self, pks, fields=("id", "name"), filters=None):
        return async_to_sync(self.service.display_name)(pks, list(fields), filters=filters)

    def test_order_of_the_pks(self):
        records = self.display_name([self.saw.pk, self.bread.pk, self.hammer.pk])

        self.assertEqual([record.name for record in records], ["Saw", "Bread", "Hammer"])

    def test_pks_as_strings(self):
        records = self.display_name([str(self.saw.pk), str(self.hammer.pk)])

        self.assertEqual([record.name for record in records], ["Saw", "Hammer"])

    @parameterized.expand(
        [
            ("unknown", lambda t: [t.saw.pk, 999]),
            ("ill-typed", lambda t: [t.saw.pk, "not-a-pk"]),
            ("repeated", lambda t: [t.saw.pk, t.saw.pk]),
        ]
    )
    def test_absent_rather_than_raised(self, dummy, pks):
        self.assertEqual([record.name for record in self.display_name(pks(self))], ["Saw"])

    def test_empty(self):
        with self.assertNumQueries(0):
            self.assertEqual(self.display_name([]), [])
            self.assertEqual(self.display_name(["not-a-pk"]), [])

    @parameterized.expand(
        [
            ("a dict, as a nested route passes", lambda t: {"category_id": t.tools.pk}),
            ("a Q", lambda t: Q(category__name="Tools")),
        ]
    )
    def test_filters(self, dummy, filters):
        records = self.display_name([self.bread.pk, self.saw.pk], filters=filters(self))

        self.assertEqual([record.name for record in records], ["Saw"])

    def test_loads_the_fields_only(self):
        # One query for the products, one for the categories they point to; nothing
        # left to load when serializing.
        with self.assertNumQueries(2):
            records = self.display_name([self.saw.pk], fields=["id", "name", "category__id", "category__name"])
            self.assertEqual(records[0].category.name, "Tools")

        self.assertEqual(records[0].get_deferred_fields(), {"rank"})
