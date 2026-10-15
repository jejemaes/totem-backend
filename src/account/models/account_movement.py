from django.db import models
from django.utils import timezone

from core.orm.fields import ULIDField


class AccountMovementQuerySet(models.QuerySet):

    def update(self, **kwargs):
        # See `AccountQuerySet.update`.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class AccountMovement(models.Model):
    """A revenue or an expense of an account.

    The amount is signed: a debit (expense) is negative, a credit (revenue)
    positive. There is no `direction` column, since it would be `sign(amount)`
    stored a second time, free to disagree with it.
    """

    id = ULIDField("ID", primary_key=True)
    account = models.ForeignKey(
        "account.Account",
        verbose_name="Account",
        related_name="movements",
        # An account with movements cannot be deleted: its history would vanish.
        on_delete=models.PROTECT,
    )
    amount = models.DecimalField(
        "Amount",
        max_digits=19,
        decimal_places=2,
        help_text="Negative for a debit (expense), positive for a credit (revenue).",
    )
    name = models.CharField("Name", max_length=255)
    description = models.TextField("Description", null=True, blank=True)
    date = models.DateField("Date", db_index=True)
    reference = models.CharField(
        "Reference", max_length=100, null=True, blank=True,
        help_text="Invoice or order number.",
    )
    category = models.ForeignKey(
        "account.AccountCategory",
        verbose_name="Category",
        related_name="movements",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = AccountMovementQuerySet.as_manager()

    class Meta:
        verbose_name = "Account Movement"
        verbose_name_plural = "Account Movements"
        indexes = [
            # Movements of one account over a period: statements and balances by
            # date, the next reads this app will need.
            models.Index(fields=["account", "date"], name="account_movement_account_date"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0),
                name="account_movement_amount_not_zero",
                violation_error_message="The amount cannot be zero.",
            ),
        ]

    def __str__(self):
        return self.name
