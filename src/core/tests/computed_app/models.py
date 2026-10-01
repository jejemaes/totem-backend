"""One model per dependency shape a stored computed field can declare.

  Order.label_upper      local fields only: becomes a `GeneratedField`
  Order.line_count       a reverse foreign key (rows joining or leaving)
  Order.total            fields of a reverse foreign key
  Order.total_of_amounts a `GeneratedField` of a reverse foreign key: watches its inputs
  Order.tag_count        a many-to-many declared here
  Order.tag_names        the same, through a prefetch method, plus a field of it
  Order.tag_popularity   a stored computed field of a many-to-many (a chain)
  Tag.order_count        a many-to-many declared on the other side
  Line.order_status      a field behind a forward foreign key
  Line.amount            local fields only: becomes a `GeneratedField`

plus one virtual field of each computation strategy on `Order`.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import models
from django.db.models import Count, F, Max, Sum
from django.db.models.functions import Upper

from core.orm.fields import ComputedField, ComputedQuerySetMixin, ULIDField


def amount_field():
    return models.DecimalField(max_digits=12, decimal_places=2)


class ComputedQuerySet(ComputedQuerySetMixin, models.QuerySet):
    pass


class Product(models.Model):
    name = models.CharField("Name", max_length=64)


class Tag(models.Model):
    name = models.CharField("Name", max_length=64)

    order_count = ComputedField(
        "Order count",
        output_field=models.IntegerField(),
        annotation_method=lambda: Count("orders"),
        depends_on=["orders"],
        stored=True,
    )

    objects = ComputedQuerySet.as_manager()


class Order(models.Model):
    id = ULIDField("ID", primary_key=True)
    label = models.CharField("Label", max_length=64, default="")
    status = models.CharField("Status", max_length=16, default="draft")
    tags = models.ManyToManyField(Tag, verbose_name="Tags", related_name="orders", blank=True)

    label_upper = ComputedField(
        "Label (upper)",
        output_field=models.CharField(max_length=64),
        annotation_method=lambda: Upper("label"),
        depends_on=["label"],
        stored=True,
    )
    line_count = ComputedField(
        "Line count",
        output_field=models.IntegerField(),
        annotation_method=lambda: Count("lines"),
        depends_on=["lines"],
        stored=True,
    )
    total = ComputedField(
        "Total",
        output_field=amount_field(),
        annotation_method=lambda: Sum(
            F("lines__quantity") * F("lines__unit_price"), default=Decimal("0")
        ),
        depends_on=["lines__quantity", "lines__unit_price"],
        stored=True,
    )
    total_of_amounts = ComputedField(
        "Total of amounts",
        output_field=amount_field(),
        annotation_method=lambda: Sum("lines__amount", default=Decimal("0")),
        depends_on=["lines__amount"],
        stored=True,
    )
    tag_count = ComputedField(
        "Tag count",
        output_field=models.IntegerField(),
        annotation_method=lambda: Count("tags"),
        depends_on=["tags"],
        stored=True,
    )
    tag_popularity = ComputedField(
        "Tag popularity",
        output_field=models.IntegerField(),
        # Reads `Tag.order_count`, itself a stored computed field: refreshed after it.
        annotation_method=lambda: Max("tags__order_count", default=0),
        depends_on=["tags__order_count"],
        stored=True,
    )
    tag_names = ComputedField(
        "Tag names",
        output_field=models.CharField(max_length=255),
        prefetch_method="prefetch_tag_names",
        depends_on=["tags", "tags__name"],
        stored=True,
    )

    line_count_virtual = ComputedField(
        "Line count (virtual)",
        output_field=models.IntegerField(),
        annotation_method=lambda: Count("lines"),
    )
    max_quantity_virtual = ComputedField(
        "Largest quantity (virtual)",
        output_field=models.IntegerField(null=True),
        prefetch_method="prefetch_max_quantity",
    )

    objects = ComputedQuerySet.as_manager()

    @classmethod
    def prefetch_tag_names(cls, instances):
        names = defaultdict(list)
        rows = cls.tags.through.objects.filter(
            order_id__in=[i.pk for i in instances]
        ).values_list("order_id", "tag__name")
        for order_id, name in rows:
            names[order_id].append(name)
        return {i.pk: ", ".join(sorted(names[i.pk])) for i in instances}

    @classmethod
    def prefetch_max_quantity(cls, instances):
        largest = {}
        rows = Line.objects.filter(order_id__in=[i.pk for i in instances]).values_list(
            "order_id", "quantity"
        )
        for order_id, quantity in rows:
            largest[order_id] = max(largest.get(order_id, quantity), quantity)
        return largest


class Line(models.Model):
    order = models.ForeignKey(Order, verbose_name="Order", related_name="lines", on_delete=models.CASCADE)
    product = models.ForeignKey(
        Product, verbose_name="Product", related_name="lines", null=True, blank=True,
        on_delete=models.CASCADE,
    )
    quantity = models.IntegerField("Quantity", default=1)
    unit_price = models.DecimalField("Unit price", max_digits=12, decimal_places=2, default=0)

    amount = ComputedField(
        "Amount",
        output_field=amount_field(),
        annotation_method=lambda: F("quantity") * F("unit_price"),
        depends_on=["quantity", "unit_price"],
        stored=True,
    )
    order_status = ComputedField(
        "Order status",
        output_field=models.CharField(max_length=16),
        annotation_method=lambda: F("order__status"),
        depends_on=["order__status"],
        stored=True,
    )

    objects = ComputedQuerySet.as_manager()
