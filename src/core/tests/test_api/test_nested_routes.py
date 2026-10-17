import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from ninja import FilterSchema
from parameterized import parameterized
from pydantic import Field

from core.api.validation import _check_path_parameters
from core.testing import APITestCaseMixin
from core.tests.computed_app.models import Category, Product
from core.tests.computed_app.schemas import ProductBodySchema, ProductCreateSchema, ProductFilterSchema
from user.tests.test_api.common import CommonTestMixin


def products_url(category, product=None):
    url = f"/api/v1/computed-app/categories/{category.pk}/products/"
    return f"{url}{product.pk}/" if product else url


class NestedRoutesAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """`CategoryProductController` nests products under
    `/categories/{category_id}/products/`: the path names the category, every route
    stays within it."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tools, cls.food = Category.objects.bulk_create([Category(name="Tools"), Category(name="Food")])
        cls.hammer, cls.saw, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=cls.tools),
            Product(name="Saw", category=cls.tools),
            Product(name="Bread", category=cls.food),
        ])

    def request(self, url, method, data=None, params=None):
        return self.do_api_request(
            url, method, self.user_access_token_frodon.token,
            data=json.dumps(data) if data is not None else None, params=params or {},
        )

    # ------------------------------------------
    # List
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the category's only", "tools", {}, ["Hammer", "Saw"]),
            ("ANDed with a filter", "tools", {"name": "ham"}, ["Hammer"]),
            # A filter cannot reach outside the path.
            ("a filter matching another category", "tools", {"name": "bread"}, []),
            ("another category", "food", {}, ["Bread"]),
        ]
    )
    def test_list(self, dummy, category, params, names):
        response = self.request(products_url(getattr(self, category)), "GET", params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.json()["results"]], names)

    def test_list_filters_in_one_where(self):
        with CaptureQueriesContext(connection) as ctx:
            self.request(products_url(self.tools), "GET", params={"name": "ham"})

        page = [q["sql"] for q in ctx.captured_queries if "computed_app_product" in q["sql"] and "COUNT" not in q["sql"]]
        self.assertEqual(len(page), 1)
        self.assertEqual(page[0].count("WHERE"), 1)

    def test_list_unknown_category(self):
        response = self.request(products_url(Category(pk=999)), "GET")

        self.assertEqual((response.status_code, response.json()["count"]), (200, 0))

    # ------------------------------------------
    # Retrieve / Update / Delete
    # ------------------------------------------

    def test_retrieve(self):
        response = self.request(products_url(self.tools, self.hammer), "GET")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"id": self.hammer.pk, "name": "Hammer", "category": {"id": self.tools.pk, "name": "Tools"}},
        )

    @parameterized.expand([("GET", None), ("PATCH", {"name": "Hacked"}), ("DELETE", None)])
    def test_another_categorys_product_is_not_found(self, method, data):
        response = self.request(products_url(self.food, self.hammer), method, data=data)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Product.objects.get(pk=self.hammer.pk).name, "Hammer")

    def test_update(self):
        response = self.request(products_url(self.tools, self.hammer), "PATCH", data={"name": "Mallet"})

        self.assertEqual((response.status_code, response.json()["name"]), (200, "Mallet"))

    def test_delete(self):
        response = self.request(products_url(self.tools, self.hammer), "DELETE")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Product.objects.filter(pk=self.hammer.pk).exists())

    # ------------------------------------------
    # Create
    # ------------------------------------------

    def test_create_files_under_the_path(self):
        response = self.request(products_url(self.food), "POST", data={"name": "Cheese"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["category"]["id"], self.food.pk)
        self.assertEqual(Product.objects.get(pk=response.json()["id"]).category_id, self.food.pk)

    def test_create_ignores_a_category_in_the_body(self):
        # Not in the body schema: the path decides.
        response = self.request(products_url(self.food), "POST", data={"name": "Cheese", "category": self.tools.pk})

        self.assertEqual((response.status_code, response.json()["category"]["id"]), (201, self.food.pk))

    def test_create_under_an_unknown_category(self):
        response = self.request(products_url(Category(pk=999)), "POST", data={"name": "Cheese"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual([d["loc"][-1] for d in response.json()["detail"]], ["category"])
        self.assertFalse(Product.objects.filter(name="Cheese").exists())


class _CategoryFilterSchema(FilterSchema):
    category: str = Field(None, q="category__id")


class PathParametersValidationTest(TestCase):
    """`_check_path_parameters`, on stand-ins: declaring a real controller would
    register its routes on the API."""

    def controller(self, prefix, filter_schema=ProductFilterSchema, create_schema=ProductBodySchema):
        return type("FakeController", (), {
            "path_prefix": prefix,
            "model": Product,
            "list_filter_schema": filter_schema,
            "create_request_schema": create_schema,
        })

    def test_valid(self):
        self.assertEqual(list(_check_path_parameters(self.controller("/categories/{category_id}/products/"))), [])

    def test_no_path_parameter(self):
        self.assertEqual(list(_check_path_parameters(self.controller("/products/"))), [])

    @parameterized.expand(
        [
            ("unknown field", {"prefix": "/shops/{shop_id}/products/"}, "is no field of Product"),
            ("filter on the path", {"filter_schema": _CategoryFilterSchema}, "already decides"),
            ("body carries the path", {"create_schema": ProductCreateSchema}, "sets"),
        ]
    )
    def test_refused(self, dummy, kwargs, message):
        kwargs.setdefault("prefix", "/categories/{category_id}/products/")
        errors = list(_check_path_parameters(self.controller(**kwargs)))

        self.assertEqual(len(errors), 1)
        self.assertIn(message, errors[0])
