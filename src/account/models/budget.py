from collections import defaultdict
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Count, Sum
from django.utils import timezone

from core.orm.fields import ComputedField, ComputedQuerySetMixin, HtmlField, ULIDField

from .account import amount_field


class BudgetQuerySet(ComputedQuerySetMixin, models.QuerySet):

    def update(self, **kwargs):
        # See `AccountQuerySet.update`.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class Budget(models.Model):
    """A forecast of an account: what is planned per category, set against what
    its movements actually amount to."""

    id = ULIDField("ID", primary_key=True)
    name = models.CharField("Name", max_length=255)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="User",
        related_name="budgets",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="The user in charge of the budget.",
    )
    account = models.ForeignKey(
        "account.Account",
        verbose_name="Account",
        related_name="budgets",
        # PROTECT rather than RESTRICT: the delete of the service reports a
        # `ProtectedError` as a validation error, a `RestrictedError` it does not.
        on_delete=models.PROTECT,
    )
    active = models.BooleanField("Active", default=True)
    note = HtmlField("Note", null=True, blank=True)

    total_planned_amount = ComputedField(
        "Total Planned Amount",
        output_field=amount_field(),
        annotation_method=lambda: Sum("positions__total_planned", default=Decimal("0")),
        depends_on=["positions", "positions__total_planned"],
        stored=True,
    )
    total_practical_amount = ComputedField(
        "Total Practical Amount",
        output_field=amount_field(),
        annotation_method=lambda: Sum("positions__total_practical", default=Decimal("0")),
        depends_on=["positions", "positions__total_practical"],
        stored=True,
    )
    # Virtual: it reads every movement of the account, so storing it would
    # recompute every budget of an account on each of its movements.
    uncategorized_movement_count = ComputedField(
        "Uncategorized Movement Count",
        output_field=models.IntegerField(),
        prefetch_method="prefetch_uncategorized_movement_count",
        help_text="Movements of the account whose category has no position in the budget, "
        "movements without category included.",
    )

    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = BudgetQuerySet.as_manager()

    class Meta:
        verbose_name = "Budget"
        verbose_name_plural = "Budgets"

    def __str__(self):
        return self.name

    @classmethod
    def prefetch_uncategorized_movement_count(cls, instances):
        from .account_movement import AccountMovement  # declared after this model
        from .budget_position import BudgetPosition

        pks = [i.pk for i in instances]
        # Read here rather than from the instances: a read restricted to the
        # count would have deferred it, and loaded it once per budget.
        accounts = dict(cls.objects.filter(pk__in=pks).values_list("pk", "account_id"))

        categories = defaultdict(set)
        for budget_id, category_id in BudgetPosition.objects.filter(
            budget_id__in=pks
        ).values_list("budget_id", "category_id"):
            categories[budget_id].add(category_id)

        counts = defaultdict(dict)  # account -> {category or None: count}
        rows = (
            AccountMovement.objects.filter(account_id__in=set(accounts.values()))
            .order_by()
            .values("account_id", "category_id")
            .annotate(n=Count("pk"))
            .values_list("account_id", "category_id", "n")
        )
        for account_id, category_id, n in rows:
            counts[account_id][category_id] = n

        return {
            pk: sum(
                n for category_id, n in counts[account_id].items()
                if category_id not in categories[pk]
            )
            for pk, account_id in accounts.items()
        }
