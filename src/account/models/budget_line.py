from django.db import models

from core.orm.fields import ULIDField


class BudgetLineQuerySet(models.QuerySet):
    """`budget` is derived from `position` on every write path of the service:
    never written by a client, never out of step with the position."""

    def bulk_create(self, objs, *args, **kwargs):
        from .budget_position import BudgetPosition

        # The service hands resolved positions over: their budget costs nothing.
        # Only a bare `position_id` is read.
        unresolved = {o.position_id for o in objs if not BudgetLine.position.is_cached(o)}
        budgets = dict(
            BudgetPosition.objects.filter(pk__in=unresolved).values_list("pk", "budget_id")
        ) if unresolved else {}
        for obj in objs:
            if BudgetLine.position.is_cached(obj):
                obj.budget_id = obj.position.budget_id
            else:
                obj.budget_id = budgets.get(obj.position_id)
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        from .budget_position import BudgetPosition

        if "position" in kwargs or "position_id" in kwargs:
            position = kwargs.get("position", kwargs.get("position_id"))
            if isinstance(position, BudgetPosition):
                kwargs["budget_id"] = position.budget_id
            else:
                kwargs["budget_id"] = (
                    BudgetPosition.objects.filter(pk=position).values_list("budget_id", flat=True).first()
                )
        return super().update(**kwargs)


class BudgetLine(models.Model):
    id = ULIDField("ID", primary_key=True)
    # A plain field: the project has no translatable field yet.
    name = models.CharField("Name", max_length=255)
    sequence = models.IntegerField("Sequence", default=10)
    position = models.ForeignKey(
        "account.BudgetPosition",
        verbose_name="Position",
        related_name="lines",
        on_delete=models.CASCADE,
    )
    planned_amount = models.DecimalField("Planned Amount", max_digits=19, decimal_places=2)
    # The budget of the position, stored: what filters the lines of a budget and
    # scopes them to its user without a join through the positions.
    budget = models.ForeignKey(
        "account.Budget",
        verbose_name="Budget",
        related_name="lines",
        on_delete=models.CASCADE,
        editable=False,
    )

    objects = BudgetLineQuerySet.as_manager()

    class Meta:
        verbose_name = "Budget Line"
        verbose_name_plural = "Budget Lines"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # The admin writes through `save()`, not through the QuerySet.
        self.budget_id = self.position.budget_id
        super().save(*args, **kwargs)
