from typing import List, Optional

from core.schemas import ModelSchema
from core.tests.computed_app.models import Line, Order, Product, Tag


class ProductCreateSchema(ModelSchema):
    class Meta:
        model = Product
        fields = ["name"]


class TagCreateSchema(ModelSchema):
    class Meta:
        model = Tag
        fields = ["name"]


class TagUpdateSchema(ModelSchema):
    class Meta:
        model = Tag
        fields = ["name"]
        optional_fields = "__all__"


class OrderCreateSchema(ModelSchema):
    tags: Optional[List[int]] = None

    class Meta:
        model = Order
        fields = ["label", "status"]
        optional_fields = ["status"]


class OrderUpdateSchema(ModelSchema):
    tags: Optional[List[int]] = None

    class Meta:
        model = Order
        fields = ["label", "status"]
        optional_fields = "__all__"


class LineCreateSchema(ModelSchema):
    class Meta:
        model = Line
        fields = ["order", "product", "quantity", "unit_price"]
        optional_fields = ["product"]


class LineUpdateSchema(ModelSchema):
    class Meta:
        model = Line
        fields = ["order", "product", "quantity", "unit_price"]
        optional_fields = "__all__"
