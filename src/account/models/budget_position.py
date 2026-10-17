from collections import defaultdict
from decimal import Decimal

from django.db import models
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce

from core.orm.fields import ComputedField, ComputedQuerySetMixin, ULIDField

from .account import amount_field


class BudgetPositionQuerySet(ComputedQuerySetMixin, models.QuerySet):
    pass


class BudgetPosition(models.Model):
    """The share of a budget planned for one category."""

    id = ULIDField("ID", primary_key=True)
    sequence = models.IntegerField("Sequence", default=10)
    budget = models.ForeignKey(
        "account.Budget",
        verbose_name="Budget",
        related_name="positions",
        on_delete=models.CASCADE,
    )
    category = models.ForeignKey(
        "account.AccountCategory",
        verbose_name="Category",
        related_name="budget_positions",
        on_delete=models.CASCADE,
    )

    name = ComputedField(
        "Name",
        output_field=models.CharField(max_length=100),
        # The category is required: "#" only stands for a row read while it
        # is being deleted.
        annotation_method=lambda: Coalesce(F("category__name"), Value("#")),
        depends_on=["category", "category__name"],
        stored=True,
    )
    color = ComputedField(
        "Color",
        output_field=models.PositiveSmallIntegerField(),
        annotation_method=lambda: F("category__color"),
        depends_on=["category", "category__color"],
        stored=True,
    )
    total_planned = ComputedField(
        "Total Planned",
        output_field=amount_field(),
        annotation_method=lambda: Sum("lines__planned_amount", default=Decimal("0")),
        depends_on=["lines", "lines__planned_amount"],
        stored=True,
    )
    total_practical = ComputedField(
        "Total Practical",
        output_field=amount_field(),
        prefetch_method="prefetch_total_practical",
        # A movement joining or leaving the category, or changing amount or
        # account; and the position changing category.
        depends_on=[
            "category",
            "budget__account",
            "category__movements",
            "category__movements__amount",
            "category__movements__account",
        ],
        stored=True,
        help_text="Sum of the movements of the budget's account in the category.",
    )

    objects = BudgetPositionQuerySet.as_manager()

    class Meta:
        verbose_name = "Budget Position"
        verbose_name_plural = "Budget Positions"
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "category"],
                name="unique_budget_position_category",
                violation_error_message="The budget already has a position for this category.",
            ),
        ]

    def __str__(self):
        return self.name or "#"

    @classmethod
    def prefetch_total_practical(cls, instances):
        from .account_movement import AccountMovement  # declared after this model

        # The keys of each position, read in one query: the instances may hold
        # neither the budget's account nor, deferred, the category.
        keys = {
            pk: (account_id, category_id)
            for pk, account_id, category_id in cls.objects.filter(
                pk__in=[i.pk for i in instances]
            ).values_list("pk", "budget__account_id", "category_id")
        }
        totals = defaultdict(lambda: Decimal("0"))
        rows = (
            AccountMovement.objects.filter(
                account_id__in={a for a, c in keys.values()},
                category_id__in={c for a, c in keys.values()},
            )
            .order_by()
            .values("account_id", "category_id")
            .annotate(total=Sum("amount"))
            .values_list("account_id", "category_id", "total")
        )
        for account_id, category_id, total in rows:
            totals[(account_id, category_id)] = total
        return {pk: totals[key] for pk, key in keys.items()}
