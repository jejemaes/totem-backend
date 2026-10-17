from typing import List

from ninja import Schema

from core.api import ModelController
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1

from .schemas import (
    LineCreateSchema,
    ProductBodySchema,
    ProductFilterSchema,
    ProductSchema,
    LineSchema,
    LineUpdateSchema,
    OrderCreateSchema,
    OrderSchema,
    OrderUpdateSchema,
)
from .services import LineService, OrderService, ProductService


class OrderController(ModelController):
    """All five operations, for any valid token: a test-only resource."""

    api = api_v1
    service = OrderService
    path_prefix = "/computed-app/orders/"
    auth = [OAuthTokenAuthentication()]

    list_response_schema: Schema = List[OrderSchema]
    # A stored computed field is a column: it can be ordered by.
    list_ordering_fields = ["label", "line_count"]
    list_ordering_default_fields = ["label"]
    retrieve_response_schema: Schema = OrderSchema
    create_request_schema = OrderCreateSchema
    create_response_schema = OrderSchema
    update_request_schema = OrderUpdateSchema
    update_response_schema = OrderSchema


class LineController(ModelController):
    """Reads its order's stored `line_count` through the relation, which is fine."""

    api = api_v1
    service = LineService
    path_prefix = "/computed-app/lines/"
    auth = [OAuthTokenAuthentication()]

    list_response_schema: Schema = List[LineSchema]
    list_ordering_fields = ["quantity"]
    list_ordering_default_fields = ["quantity"]
    retrieve_response_schema: Schema = LineSchema
    create_request_schema = LineCreateSchema
    create_response_schema = LineSchema
    update_request_schema = LineUpdateSchema
    update_response_schema = LineSchema


class CategoryProductController(ModelController):
    """Nested: the products of the category named by the path, which a creation
    files them under."""

    api = api_v1
    service = ProductService
    path_prefix = "/computed-app/categories/{category_id}/products/"
    auth = [OAuthTokenAuthentication()]

    list_response_schema: Schema = List[ProductSchema]
    list_filter_schema = ProductFilterSchema
    list_ordering_fields = ["name"]
    list_ordering_default_fields = ["name"]
    retrieve_response_schema: Schema = ProductSchema
    create_request_schema = ProductBodySchema
    create_response_schema = ProductSchema
    update_request_schema = ProductBodySchema
    update_response_schema = ProductSchema
