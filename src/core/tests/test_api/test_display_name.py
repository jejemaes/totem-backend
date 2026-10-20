from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from core.tests.computed_app.models import Category, Order, Product
from user.tests.test_api.common import CommonTestMixin


class DisplayNameRouteAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """`GET .../display-name/?id=...`, on `OrderController` (ULID pk) and on the
    nested `CategoryProductController` (integer pk)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tools, cls.food = Category.objects.bulk_create([Category(name="Tools"), Category(name="Food")])
        cls.hammer, cls.saw, cls.bread = Product.objects.bulk_create([
            Product(name="Hammer", category=cls.tools),
            Product(name="Saw", category=cls.tools),
            Product(name="Bread", category=cls.food),
        ])
        cls.first, cls.second = Order.objects.bulk_create([Order(label="first"), Order(label="second")])

    def request(self, url, ids=None):
        params = {"id": ids} if ids is not None else {}
        return self.do_api_request(url, "GET", self.user_access_token_frodon.token, params=params)

    def products_url(self, category):
        return f"/api/v1/computed-app/categories/{category.pk}/products/display-name/"

    def test_response(self):
        response = self.request("/api/v1/computed-app/orders/display-name/", f"{self.second.pk},{self.first.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(item["id"], item["label"]) for item in response.json()],
            [(str(self.second.pk), "second"), (str(self.first.pk), "first")],
        )
        self.assertEqual(set(response.json()[0]), {"id", "label", "line_count"})

    def test_nested(self):
        # Registered before `/{id}/`: not taken for the id `display-name`. Bread is
        # another category's: absent, as an unknown id.
        response = self.request(self.products_url(self.tools), f"{self.saw.pk}, {self.bread.pk},{self.hammer.pk},")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"id": self.saw.pk, "name": "Saw", "category": {"id": self.tools.pk, "name": "Tools"}},
                {"id": self.hammer.pk, "name": "Hammer", "category": {"id": self.tools.pk, "name": "Tools"}},
            ],
        )

    def test_unknown_ids(self):
        response = self.request(self.products_url(self.tools), "999")

        self.assertEqual((response.status_code, response.json()), (200, []))

    @parameterized.expand(
        [
            ("missing", "orders", None),
            ("malformed ULID", "orders", "not-a-ulid"),
            ("not an integer", "products", "saw"),
        ]
    )
    def test_invalid(self, dummy, resource, ids):
        url = (
            "/api/v1/computed-app/orders/display-name/" if resource == "orders"
            else self.products_url(self.tools)
        )
        response = self.request(url, ids)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])


class DisplayNameDeclarationTest(TestCase):

    def test_schema_is_required(self):
        from core.api import DisplayNameModelControllerMixin, ModelController
        from core.tests.computed_app.services import CategoryService

        with self.assertRaises(ImproperlyConfigured) as ctx:
            class CategoryDisplayNameController(DisplayNameModelControllerMixin, ModelController):  # pylint: disable=unused-variable
                service = CategoryService

        self.assertIn("no display_name_response_schema", str(ctx.exception))

    @parameterized.expand(
        [
            ("well placed", ["display_name", "retrieve", "update", "delete"], None),
            ("never registered", ["retrieve", "update", "delete"], "registers no /display-name/ route"),
            ("after /{id}/", ["retrieve", "display_name"], "registered after the /{id}/ routes (retrieve)"),
        ]
    )
    def test_route_order(self, dummy, routes, message):
        from core.api import DisplayNameModelControllerMixin
        from core.api.validation import _check_display_name_route

        controller = type(
            "StandInController", (DisplayNameModelControllerMixin,),
            {"model": Product, **{name: lambda self: None for name in routes}},
        )
        errors = list(_check_display_name_route(controller))

        if message is None:
            self.assertEqual(errors, [])
        else:
            self.assertEqual(len(errors), 1)
            self.assertIn(message, errors[0])

    def test_real_controllers_are_well_placed(self):
        from core.api.validation import _check_display_name_route
        from core.tests.computed_app.api import CategoryProductController, OrderController

        for controller in (CategoryProductController, OrderController):
            self.assertEqual(list(_check_display_name_route(controller)), [])

    def test_permission_map_requires_display_name(self):
        from core.api import DisplayNameModelControllerMixin
        from user.security import TokenHasScopePermissionModelControllerMixin

        controller = type(
            "StandInController",
            (TokenHasScopePermissionModelControllerMixin, DisplayNameModelControllerMixin),
            {"permission_map": {"read": ["totem.contact.read"]}},
        )
        with self.assertRaises(ImproperlyConfigured) as ctx:
            controller._display_name_function_decorators()

        self.assertIn("no 'display_name' scopes", str(ctx.exception))
