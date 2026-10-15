from decimal import Decimal

from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q, Sum
from django.utils import timezone

from core.orm.fields import ComputedField, ComputedQuerySetMixin, ULIDField

ACCOUNT_CODE_PATTERN = r"^[A-Z0-9_-]{1,50}$"


def amount_field():
    return models.DecimalField(max_digits=19, decimal_places=2)


class AccountQuerySet(ComputedQuerySetMixin, models.QuerySet):

    def update(self, **kwargs):
        # `auto_now` lives in `DateTimeField.pre_save()`, which only runs on
        # `Model.save()`; the service layer writes through `queryset.update()`.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class Account(models.Model):
    id = ULIDField("ID", primary_key=True)
    name = models.CharField("Name", max_length=255, unique=True)
    code = models.CharField(
        "Code",
        max_length=50,
        unique=True,
        # Becomes the `pattern` of the generated pydantic field, so a bad code is
        # refused before any query. The check constraint below covers the ORM side.
        validators=[RegexValidator(ACCOUNT_CODE_PATTERN)],
        help_text="Upper case letters, digits, '_' and '-' only.",
    )
    description = models.TextField("Description", null=True, blank=True)
    active = models.BooleanField("Active", default=True)

    # Stored rather than virtual: read with the row, so listing accounts costs no
    # extra query, and they can be ordered by. Kept in sync by the service layer on
    # every movement write; prefetch mode because each total is one grouped query
    # over the movements of the refreshed accounts.
    total_debit = ComputedField(
        "Total Debit",
        output_field=amount_field(),
        prefetch_method="prefetch_total_debit",
        depends_on=["movements", "movements__amount"],
        stored=True,
        help_text="Sum of the negative movements (expenses), as a negative amount.",
    )
    total_credit = ComputedField(
        "Total Credit",
        output_field=amount_field(),
        prefetch_method="prefetch_total_credit",
        depends_on=["movements", "movements__amount"],
        stored=True,
        help_text="Sum of the positive movements (revenues).",
    )
    # Only reads its own row, so `ComputedField` returns a `GeneratedField`:
    # PostgreSQL recomputes it in the very UPDATE refreshing the two totals, rather
    # than a third grouped read over the movements.
    balance = ComputedField(
        "Balance",
        output_field=amount_field(),
        annotation_method=lambda: F("total_credit") + F("total_debit"),
        depends_on=["total_credit", "total_debit"],
        stored=True,
        help_text="Total credit plus total debit: the sum of every movement.",
    )

    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = AccountQuerySet.as_manager()

    class Meta:
        verbose_name = "Account"
        verbose_name_plural = "Accounts"
        constraints = [
            models.CheckConstraint(
                condition=Q(code__regex=ACCOUNT_CODE_PATTERN),
                name="account_code_format",
                violation_error_message="The code may only contain upper case letters, digits, '_' and '-'.",
            ),
        ]

    def __str__(self):
        return f"[{self.code}] {self.name}"

    # Computed fields

    @classmethod
    def _sum_movements(cls, instances, condition=None):
        """`{pk: sum of the amounts}` of the given accounts' movements matching
        `condition`. An account with none reads `0`, not None: a missing pk would
        be stored as NULL."""
        from .account_movement import AccountMovement  # declared after this model

        movements = AccountMovement.objects.filter(account_id__in=[i.pk for i in instances])
        if condition is not None:
            movements = movements.filter(condition)
        totals = dict(
            movements.order_by()
            .values("account_id")
            .annotate(total=Sum("amount"))
            .values_list("account_id", "total")
        )
        return {i.pk: totals.get(i.pk, Decimal("0")) for i in instances}

    @classmethod
    def prefetch_total_debit(cls, instances):
        return cls._sum_movements(instances, Q(amount__lt=0))

    @classmethod
    def prefetch_total_credit(cls, instances):
        return cls._sum_movements(instances, Q(amount__gt=0))
