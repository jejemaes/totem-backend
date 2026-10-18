from core.services import ServiceBase
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
    CreateMixin[ProductCreateSchema], ReadMixin, UpdateMixin[ProductUpdateSchema], DeleteMixin,
    ResequenceMixin, ServiceBase[Product],
):
    sequence_field = "rank"


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
