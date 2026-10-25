import json
from decimal import Decimal

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from core.tests.computed_app.models import Category, Line, Order, Product
from totem.api import api_v1
from user.tests.test_api.common import CommonTestMixin


class GroupByRouteAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """`POST .../group-by/`, on `LineController` and on the nested
    `CategoryProductController`."""

    url = "/api/v1/computed-app/lines/group-by/"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tools, cls.food = Category.objects.bulk_create([Category(name="Tools"), Category(name="Food")])
        cls.hammer, cls.saw, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=cls.tools, rank=1),
            Product(name="Saw", category=cls.tools, rank=1),
            Product(name="Bread", category=cls.food, rank=1),
        ])
        cls.first, cls.second = Order.objects.bulk_create([
            Order(label="first", status="draft"), Order(label="second", status="done"),
        ])
        Line.objects.bulk_create([
            Line(order=cls.first, product=cls.hammer, quantity=1, unit_price=Decimal("10.00")),
            Line(order=cls.first, product=cls.hammer, quantity=2, unit_price=Decimal("10.00")),
            Line(order=cls.second, product=cls.bread, quantity=4, unit_price=Decimal("1.50")),
        ])

    def request(self, data, url=None):
        return self.do_api_request(
            url or self.url, "POST", self.user_access_token_frodon.token, data=json.dumps(data)
        )

    def test_response(self):
        response = self.request({
            "group_by_fields": ["order", "product"],
            "measures": ["count", "quantity_sum", "amount_sum"],
            "ordering": ["-quantity_sum"],
        })

        self.assertEqual(response.status_code, 200)
        # Only the keys asked. `order` as the list renders it, `product` -- a bare
        # pk in the list -- as its pk.
        self.assertEqual(
            response.json(),
            {
                "count": 2,
                "results": [
                    {
                        "order": {"id": str(self.second.pk), "label": "second", "line_count": None},
                        "product": self.bread.pk,
                        "count": 1, "quantity_sum": 4, "amount_sum": "6.00",
                    },
                    {
                        "order": {"id": str(self.first.pk), "label": "first", "line_count": None},
                        "product": self.hammer.pk,
                        "count": 2, "quantity_sum": 3, "amount_sum": "30.00",
                    },
                ],
            },
        )

    def test_filters(self):
        response = self.request({"group_by_fields": ["order"], "measures": ["count"], "filters": {"status": "done"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([group["order"]["id"] for group in response.json()["results"]], [str(self.second.pk)])

    def test_pagination(self):
        response = self.request({"group_by_fields": ["quantity"], "measures": ["count"], "limit": 1, "offset": 1})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"count": 3, "results": [{"quantity": 2, "count": 1}]})

    def test_nested(self):
        # The path narrows to the products of the category, the filters further.
        url = f"/api/v1/computed-app/categories/{self.tools.pk}/products/group-by/"

        response = self.request({"group_by_fields": ["rank"], "measures": ["count"]}, url=url)
        self.assertEqual(response.json(), {"count": 1, "results": [{"rank": 1, "count": 2}]})

        response = self.request({"group_by_fields": ["rank"], "measures": ["count"], "filters": {"name": "saw"}}, url=url)
        self.assertEqual(response.json(), {"count": 1, "results": [{"rank": 1, "count": 1}]})

    @parameterized.expand(
        [
            ("no dimension", {"group_by_fields": []}, ["group_by_fields"]),
            ("unknown dimension", {"group_by_fields": ["unit_price"]}, ["group_by_fields", 0]),
            ("too many dimensions", {"group_by_fields": ["order", "product", "quantity", "order_status"]}, ["group_by_fields"]),
            # Reported by the service, under the name of the body.
            ("repeated dimension", {"group_by_fields": ["order", "order"]}, ["group_by_fields"]),
            ("unknown measure", {"measures": ["unit_price_sum"]}, ["measures", 0]),
            ("ordering not asked", {"ordering": ["-amount_sum"]}, ["ordering"]),
            ("ordering unknown", {"ordering": ["unit_price"]}, ["ordering", 0]),
            ("limit too large", {"limit": 1001}, ["limit"]),
            ("offset without limit", {"limit": None, "offset": 2}, ["offset"]),
        ]
    )
    def test_request_field_validation(self, dummy, body, loc):
        response = self.request({"group_by_fields": ["order"], "measures": ["count"], **body})

        self.assertEqual(response.status_code, 422)
        self.assertEqual([error["loc"] for error in response.json()["detail"]], [["body", "request_body", *loc]])

    def test_openapi(self):
        components = api_v1.get_openapi_schema()["components"]["schemas"]

        request = components["LineGroupBySchema"]["properties"]
        self.assertEqual(
            request["group_by_fields"]["items"]["enum"], ["order", "product", "order_status", "quantity"]
        )
        self.assertEqual(
            request["measures"]["items"]["enum"],
            ["count", "quantity_sum", "quantity_avg", "quantity_min", "quantity_max", "amount_sum", "quantity_share"],
        )
        self.assertIn("-quantity_share", request["ordering"]["items"]["enum"])
        self.assertIn("filters", request)
        group = components["LineGroupSchema"]["properties"]
        self.assertEqual(group["quantity_sum"]["title"], "Sum of Quantity")


class GroupByDeclarationTest(TestCase):

    def test_service_is_required(self):
        from core.api import GroupByModelControllerMixin, ModelController
        from core.tests.computed_app.services import CategoryService

        with self.assertRaises(ImproperlyConfigured) as ctx:
            class CategoryGroupByController(GroupByModelControllerMixin, ModelController):  # pylint: disable=unused-variable
                service = CategoryService

        self.assertIn("provides no `group_by`", str(ctx.exception))

    @parameterized.expand(
        [
            ("well placed", ["group_by", "retrieve", "update", "delete"], None),
            ("never registered", ["retrieve", "update", "delete"], "registers no /group-by/ route"),
            ("after /{id}/", ["retrieve", "group_by"], "registered after the /{id}/ routes (retrieve)"),
        ]
    )
    def test_route_order(self, dummy, routes, message):
        from core.api import GroupByModelControllerMixin
        from core.api.validation import _check_group_by_route

        controller = type(
            "StandInController", (GroupByModelControllerMixin,),
            {"model": Line, **{name: lambda self: None for name in routes}},
        )
        errors = list(_check_group_by_route(controller))

        if message is None:
            self.assertEqual(errors, [])
        else:
            self.assertEqual(len(errors), 1)
            self.assertIn(message, errors[0])

    def test_real_controllers_are_well_placed(self):
        from core.api.validation import _check_group_by_route
        from core.tests.computed_app.api import CategoryProductController, LineController

        for controller in (CategoryProductController, LineController):
            self.assertEqual(list(_check_group_by_route(controller)), [])

    def test_permission_map_requires_group_by(self):
        from core.api import GroupByModelControllerMixin
        from user.security import TokenHasScopePermissionModelControllerMixin

        controller = type(
            "StandInController",
            (TokenHasScopePermissionModelControllerMixin, GroupByModelControllerMixin),
            {"permission_map": {"read": ["totem.contact.read"]}},
        )
        with self.assertRaises(ImproperlyConfigured) as ctx:
            controller._group_by_function_decorators()

        self.assertIn("no 'group_by' scopes", str(ctx.exception))
