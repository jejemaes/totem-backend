from core.services import ServiceBase
from core.services.mixins import CreateMixin, DeleteMixin, ReadMixin, UpdateMixin

from .models import Line, Order, Product, Tag
from .schemas import (
    LineCreateSchema,
    LineUpdateSchema,
    OrderCreateSchema,
    OrderUpdateSchema,
    ProductCreateSchema,
    TagCreateSchema,
    TagUpdateSchema,
)


class ProductService(CreateMixin[ProductCreateSchema], ReadMixin, DeleteMixin, ServiceBase[Product]):
    pass


class TagService(
    CreateMixin[TagCreateSchema], ReadMixin, UpdateMixin[TagUpdateSchema], DeleteMixin, ServiceBase[Tag]
):
    pass


class OrderService(
    CreateMixin[OrderCreateSchema], ReadMixin, UpdateMixin[OrderUpdateSchema], DeleteMixin, ServiceBase[Order]
):
    pass


class LineService(
    CreateMixin[LineCreateSchema], ReadMixin, UpdateMixin[LineUpdateSchema], DeleteMixin, ServiceBase[Line]
):
    pass
