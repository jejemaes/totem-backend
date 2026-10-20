from typing import List, Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from core.tests.computed_app.models import Category, Line, Order, Product, Tag


class CategoryCreateSchema(ModelSchema):
    class Meta:
        model = Category
        fields = ["name"]


class CategoryUpdateSchema(ModelSchema):
    class Meta:
        model = Category
        fields = ["name"]
        optional_fields = "__all__"


class ProductCreateSchema(ModelSchema):
    class Meta:
        model = Product
        fields = ["name", "category"]
        optional_fields = ["category"]


class ProductUpdateSchema(ModelSchema):
    class Meta:
        model = Product
        fields = ["name", "category"]
        optional_fields = "__all__"


class CategoryDisplayNameSchema(ModelSchema):
    class Meta:
        model = Category
        fields = ["id", "name"]


class ProductSchema(ModelSchema):
    # Annotated, or the relation would be read lazily, from the async route.
    category: Optional[CategoryDisplayNameSchema] = None

    class Meta:
        model = Product
        fields = ["id", "name", "rank", "category"]


class ProductDisplayNameSchema(ModelSchema):
    # A relation: `display_name` must load it, or the async route reads it lazily.
    category: Optional[CategoryDisplayNameSchema] = None

    class Meta:
        model = Product
        fields = ["id", "name", "category"]


class ProductBodySchema(ModelSchema):
    """The body of the nested route: the category comes from its path."""

    class Meta:
        model = Product
        fields = ["name"]


class ProductFilterSchema(FilterSchema):
    name: Optional[str] = Field(None, q="name__icontains")


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


# Responses: computed fields are listed in `Meta.fields` like any other -- stored,
# virtual or generated -- typed after their `output_field`.


class OrderSchema(ModelSchema):
    class Meta:
        model = Order
        fields = [
            "id", "label", "status",
            "label_upper", "line_count", "total", "total_of_amounts", "tag_names",
            "line_count_virtual", "max_quantity_virtual",
        ]


class OrderDisplayNameSchema(ModelSchema):
    class Meta:
        model = Order
        fields = ["id", "label", "line_count"]


class LineSchema(ModelSchema):
    order: OrderDisplayNameSchema

    class Meta:
        model = Line
        fields = ["id", "order", "quantity", "unit_price", "amount", "order_status"]
