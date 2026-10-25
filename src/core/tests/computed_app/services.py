from core.services import Dimension, GroupByMixin, ServiceBase, number_measures, share_measure
from core.services.mixins import CreateMixin, DeleteMixin, ReadMixin, ResequenceMixin, UpdateMixin

from .models import Category, Line, Order, Product, Tag
from .schemas import (
    CategoryCreateSchema,
    CategoryUpdateSchema,
    LineCreateSchema,
    LineUpdateSchema,
    OrderCreateSchema,
    OrderUpdateSchema,
    ProductCreateSchema,
    ProductUpdateSchema,
    TagCreateSchema,
    TagUpdateSchema,
)


class CategoryService(
    CreateMixin[CategoryCreateSchema], ReadMixin, UpdateMixin[CategoryUpdateSchema], DeleteMixin,
    ServiceBase[Category],
):
    pass


class ProductService(
    CreateMixin[ProductCreateSchema], ReadMixin, GroupByMixin, UpdateMixin[ProductUpdateSchema], DeleteMixin,
    ResequenceMixin, ServiceBase[Product],
):
    sequence_field = "rank"
    group_by_dimensions = {"rank": Dimension("rank")}


class TagService(
    CreateMixin[TagCreateSchema], ReadMixin, UpdateMixin[TagUpdateSchema], DeleteMixin, ServiceBase[Tag]
):
    pass


class OrderService(
    CreateMixin[OrderCreateSchema], ReadMixin, UpdateMixin[OrderUpdateSchema], DeleteMixin, ServiceBase[Order]
):
    pass


class LineService(
    CreateMixin[LineCreateSchema], ReadMixin, GroupByMixin, UpdateMixin[LineUpdateSchema], DeleteMixin,
    ServiceBase[Line],
):
    # A relation rendered by the list (`order`) and one that is not (`product`), a
    # stored computed field, a plain column.
    group_by_dimensions = {
        "order": Dimension("order"),
        "product": Dimension("product"),
        "order_status": Dimension("order_status"),
        "quantity": Dimension("quantity"),
    }
    group_by_measures = {
        **number_measures("quantity"),
        # A generated column: typed after its `output_field`.
        **number_measures("amount", ["sum"]),
        **share_measure("quantity", exclude=["product"]),
    }
