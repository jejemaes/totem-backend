from asgiref.sync import async_to_sync
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.test import TestCase
from parameterized import parameterized

from core.services import Environment, ResequenceMixin, ServiceBase
from core.services.exceptions import ServiceValidationMultiError
from core.services.registry import ServiceRegistry
from core.tests.computed_app.models import Category, Customer, Product
from core.tests.computed_app.services import ProductService


class TestResequenceMixin(TestCase):
    """On `ProductService`, whose `sequence_field` is `rank`."""

    @classmethod
    def setUpTestData(cls):
        cls.tools, cls.food = Category.objects.bulk_create([Category(name="Tools"), Category(name="Food")])
        cls.hammer, cls.saw, cls.drill, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=cls.tools, rank=7),
            Product(name="Saw", category=cls.tools, rank=7),
            Product(name="Drill", category=cls.tools, rank=7),
            Product(name="Bread", category=cls.food, rank=7),
        ])

    def setUp(self):
        super().setUp()
        self.service = Environment(None).get(ProductService)

    def ranks(self):
        return dict(Product.objects.values_list("name", "rank"))

    # ------------------------------------------
    # Numbering
    # ------------------------------------------

    def test_numbers_in_the_order_given(self):
        # The pks read, then one UPDATE whatever the number of records.
        with self.assertNumQueries(4):  # savepoint, read, update, release
            count = async_to_sync(self.service.resequence)([self.drill.pk, self.hammer.pk, self.saw.pk])

        self.assertEqual(count, 3)
        self.assertEqual(self.ranks(), {"Drill": 1, "Hammer": 2, "Saw": 3, "Bread": 7})

    @parameterized.expand([(0, [1, 2, 3]), (20, [21, 22, 23])])
    def test_offset(self, offset, ranks):
        # A page of a list: numbered where it sits in the whole list.
        async_to_sync(self.service.resequence)(
            [self.drill.pk, self.hammer.pk, self.saw.pk], offset=offset
        )

        self.assertEqual([self.ranks()[name] for name in ("Drill", "Hammer", "Saw")], ranks)
        self.assertEqual(self.ranks()["Bread"], 7)

    def test_partial_list(self):
        async_to_sync(self.service.resequence)([self.saw.pk, self.hammer.pk])

        # The others are left as they were.
        self.assertEqual(self.ranks(), {"Saw": 1, "Hammer": 2, "Drill": 7, "Bread": 7})

    def test_pks_as_strings(self):
        # What a client may send: converted with the pk field.
        async_to_sync(self.service.resequence)([str(self.saw.pk), str(self.hammer.pk)])

        self.assertEqual((self.ranks()["Saw"], self.ranks()["Hammer"]), (1, 2))

    def test_empty_list(self):
        with self.assertNumQueries(0):
            self.assertEqual(async_to_sync(self.service.resequence)([]), 0)

    @parameterized.expand(
        [
            ("a dict, as a nested route passes", lambda t: {"category": t.tools.pk}),
            ("a Q", lambda t: Q(category__name="Tools")),
        ]
    )
    def test_filters(self, dummy, filters):
        filters = filters(self)
        async_to_sync(self.service.resequence)([self.saw.pk, self.hammer.pk], filters)

        self.assertEqual((self.ranks()["Saw"], self.ranks()["Hammer"]), (1, 2))

    # ------------------------------------------
    # All or nothing
    # ------------------------------------------

    @parameterized.expand(
        [
            ("unknown", lambda t: [t.saw.pk, 999]),
            ("ill-typed", lambda t: [t.saw.pk, "not-a-pk"]),
            ("repeated", lambda t: [t.saw.pk, t.hammer.pk, t.saw.pk]),
        ]
    )
    def test_invalid(self, dummy, pks):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.resequence)(pks(self))

        self.assertEqual(list(ctx.exception.dict()), ["ids"])
        self.assertEqual(set(self.ranks().values()), {7})

    def test_out_of_filters(self):
        # Bread exists, but not in the category the path names: unknown there.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.resequence)([self.saw.pk, self.bread.pk], {"category": self.tools.pk})

        self.assertIn(str(self.bread.pk), ctx.exception.dict()["ids"]["ids"][0])
        self.assertEqual(set(self.ranks().values()), {7})

    # ------------------------------------------
    # Declaration
    # ------------------------------------------

    def test_sequence_field_must_exist(self):
        self.addCleanup(ServiceRegistry._by_model.pop, Customer, None)

        with self.assertRaises(ImproperlyConfigured) as ctx:
            class CustomerService(ResequenceMixin, ServiceBase[Customer]):  # pylint: disable=unused-variable
                pass

        self.assertIn("'sequence'", str(ctx.exception))
