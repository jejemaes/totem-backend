import json
from decimal import Decimal

from django.test import TestCase

from core.orm.fields.computed import RefreshComputedFieldsContext
from core.testing import APITestCaseMixin
from core.tests.computed_app.models import Line, Order, Tag
from user.tests.test_api.common import CommonTestMixin

ORDERS_URL = "/api/v1/computed-app/orders/"
LINES_URL = "/api/v1/computed-app/lines/"


class ComputedFieldsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """Every route serializes computed values -- stored, generated and virtual --
    from an async view: a value left unloaded would query from the coroutine and
    raise `SynchronousOnlyOperation`, which the test client turns into an error."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        orders = Order.objects.bulk_create([Order(label="first"), Order(label="second")])
        lines = Line.objects.bulk_create([
            Line(order=orders[0], quantity=2, unit_price=Decimal("1.50")),
            Line(order=orders[0], quantity=5, unit_price=Decimal("1")),
        ])
        with RefreshComputedFieldsContext() as ctx:
            ctx.created(orders)
            ctx.created(lines)
        cls.order, cls.other = orders
        cls.tag = Tag.objects.create(name="red")

    @property
    def token(self):
        return self.user_access_token_frodon.token

    def request(self, url, method, data=None, params=None):
        response = self.do_api_request(
            url, method, self.token, data=json.dumps(data) if data is not None else None,
            params=params or {},
        )
        return response, response.json()

    def test_list(self):
        response, data = self.request(ORDERS_URL, "GET")
        self.assertEqual(response.status_code, 200, data)
        first = data["results"][0]
        self.assertEqual(first["label_upper"], "FIRST")       # generated
        self.assertEqual(first["line_count"], 2)              # stored
        self.assertEqual(Decimal(first["total"]), Decimal("8.00"))
        self.assertEqual(first["line_count_virtual"], 2)      # virtual, annotation
        self.assertEqual(first["max_quantity_virtual"], 5)    # virtual, prefetch

    def test_list_query_fields(self):
        response, data = self.request(
            ORDERS_URL, "GET", params={"fields": "id,line_count_virtual,max_quantity_virtual"}
        )
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual(
            data["results"][0],
            {"id": self.order.pk, "line_count_virtual": 2, "max_quantity_virtual": 5},
        )

    def test_list_ordered_by_a_stored_field(self):
        response, data = self.request(ORDERS_URL, "GET", params={"ordering": "line_count"})
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual([o["label"] for o in data["results"]], ["second", "first"])

    def test_retrieve(self):
        response, data = self.request(f"{ORDERS_URL}{self.order.pk}/", "GET")
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual((data["line_count"], data["line_count_virtual"]), (2, 2))

    def test_create(self):
        response, data = self.request(ORDERS_URL, "POST", {"label": "new", "tags": [self.tag.pk]})
        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(data["label_upper"], "NEW")
        self.assertEqual(data["tag_names"], "red")
        self.assertEqual((data["line_count"], data["line_count_virtual"]), (0, 0))
        self.assertIsNone(data["max_quantity_virtual"])

    def test_create_line_responds_with_its_refreshed_order(self):
        response, data = self.request(
            LINES_URL, "POST", {"order": self.other.pk, "quantity": 3, "unit_price": "2"}
        )
        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(Decimal(data["amount"]), Decimal("6.00"))  # generated
        self.assertEqual(data["order_status"], "draft")              # stored
        # refetched after the flush: the order already counts the new line
        self.assertEqual(data["order"]["line_count"], 1)

    def test_update(self):
        response, data = self.request(
            f"{ORDERS_URL}{self.order.pk}/", "PATCH", {"label": "renamed", "tags": [self.tag.pk]}
        )
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual(data["label_upper"], "RENAMED")
        self.assertEqual(data["tag_names"], "red")
        self.assertEqual(data["line_count_virtual"], 2)

    def test_computed_fields_are_not_writable(self):
        """They are not in the input schemas, so ninja drops them from the body."""
        response, data = self.request(
            f"{ORDERS_URL}{self.order.pk}/", "PATCH", {"label": "x", "line_count": 99}
        )
        self.assertEqual(response.status_code, 200, data)
        self.assertEqual(data["line_count"], 2)
