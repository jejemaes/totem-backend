import json
from decimal import Decimal

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from django.test import TestCase
from parameterized import parameterized
from pydantic import Field

from core.api.filters import FilterSchema, MultiValue
from core.testing import APITestCaseMixin
from core.tests.computed_app.models import Category, Line, Order, Product
from totem.api import api_v1
from user.tests.test_api.common import CommonTestMixin


class MultiValueFilterAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """`MultiValue` filters, on `LineController`: `status` (a choice-like column),
    `product` (a nullable foreign key, int pk) and `order` (never null, ULID pk)."""

    url = "/api/v1/computed-app/lines/"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tools = Category.objects.create(name="Tools")
        cls.hammer, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=tools), Product(name="Bread"),
        ])
        cls.first, cls.second = Order.objects.bulk_create([
            Order(label="first", status="draft"), Order(label="second", status="done"),
        ])
        cls.l1, cls.l2, cls.l3, cls.l4 = Line.objects.bulk_create([
            Line(order=cls.first, product=cls.hammer, quantity=1, unit_price=Decimal("10.00")),
            Line(order=cls.first, product=cls.bread, quantity=2, unit_price=Decimal("1.50")),
            Line(order=cls.second, product=cls.bread, quantity=4, unit_price=Decimal("1.50")),
            Line(order=cls.second, product=None, quantity=8, unit_price=Decimal("1.00")),
        ])

    def list(self, params):
        return self.do_api_request(self.url, "GET", self.user_access_token_frodon.token, params=params)

    def assert_lines(self, response, lines):
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(sorted(item["id"] for item in response.json()["results"]), sorted(line.pk for line in lines))

    def test_single_value(self):
        # As before the field was multi-valued.
        self.assert_lines(self.list({"status": "done"}), [self.l3, self.l4])
        self.assert_lines(self.list({"product": self.hammer.pk}), [self.l1])

    def test_comma_separated(self):
        self.assert_lines(self.list({"status": "draft,done"}), [self.l1, self.l2, self.l3, self.l4])
        self.assert_lines(self.list({"product": f"{self.hammer.pk}, {self.bread.pk}"}), [self.l1, self.l2, self.l3])
        self.assert_lines(self.list({"order": f"{self.first.pk},{self.second.pk}"}), [self.l1, self.l2, self.l3, self.l4])

    def test_null_sentinel(self):
        self.assert_lines(self.list({"product": "null"}), [self.l4])
        self.assert_lines(self.list({"product": f"{self.hammer.pk},null"}), [self.l1, self.l4])

    def test_empty_is_no_filter(self):
        self.assert_lines(self.list({"product": ""}), [self.l1, self.l2, self.l3, self.l4])

    def test_repeated_parameter(self):
        # Tolerated, not documented: each occurrence is split in turn.
        response = self.client.get(
            self.url,
            {"product": [str(self.hammer.pk), "null"], "status": ["draft,done"]},
            HTTP_AUTHORIZATION=f"Bearer {self.user_access_token_frodon.token}",
        )

        self.assert_lines(response, [self.l1, self.l4])

    def test_filters_combine_with_and(self):
        self.assert_lines(self.list({"status": "done", "product": f"{self.bread.pk},null"}), [self.l3, self.l4])

    @parameterized.expand(
        [
            ("null on a never-null lookup", {"order": "null"}, "order", 0),
            ("a malformed ULID", {"order": "not-a-ulid"}, "order", 0),
            ("a malformed int among valid ones", {"product": "1,two"}, "product", 1),
        ]
    )
    def test_invalid(self, dummy, params, field, index):
        response = self.list(params)

        self.assertEqual(response.status_code, 422)
        # The index of the faulty item follows the field name.
        self.assertEqual([error["loc"][-2:] for error in response.json()["detail"]], [[field, index]])

    @parameterized.expand(
        [
            ("a comma-separated string", lambda self: f"{self.hammer.pk},null"),
            ("a list", lambda self: [self.hammer.pk, "null"]),
        ]
    )
    def test_group_by_body(self, dummy, value):
        response = self.do_api_request(
            f"{self.url}group-by/", "POST", self.user_access_token_frodon.token,
            data=json.dumps({"group_by_fields": ["order"], "measures": ["quantity_sum"], "filters": {"product": value(self)}}),
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            {group["order"]["id"]: group["quantity_sum"] for group in response.json()["results"]},
            {str(self.first.pk): 1, str(self.second.pk): 8},
        )

    def test_openapi_documents_a_string(self):
        # The type the single-valued field had: a generated client sees no change.
        schema = api_v1.get_openapi_schema()
        parameters = {
            parameter["name"]: parameter["schema"]
            for parameter in schema["paths"][self.url]["get"]["parameters"]
        }

        for name in ("status", "product", "order"):
            self.assertEqual(parameters[name].get("type"), "string", name)


class MultiValueFilterSchemaTest(TestCase):

    def test_q_must_be_a_single_lookup(self):
        class Schema(FilterSchema):
            name: MultiValue(str) = Field(None, q=["name", "label"])

        with self.assertRaises(ImproperlyConfigured):
            Schema(name="a,b").get_filter_expression()

    def test_filter_method_receives_the_list(self):
        class Schema(FilterSchema):
            name: MultiValue(str) = Field(None)

            def filter_name(self, value):
                return Q(name__in=[v.upper() for v in value if v])

        self.assertEqual(Schema(name="a,null").get_filter_expression(), Q(name__in=["A"]))

    def test_field_name_is_the_default_lookup(self):
        class Schema(FilterSchema):
            name: MultiValue(str) = Field(None)

        self.assertEqual(Schema(name="a,null").get_filter_expression(), Q(name__in=["a"]) | Q(name__isnull=True))
