from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from base.choices import CurrencyCode
from core.orm.fields import ULIDField
from payment.choices import PaymentDirection, PaymentState, PaymentTargetType


class PaymentQuerySet(models.QuerySet):
    """`done_date` follows `state` on every write path: set when a payment becomes
    `done`, kept while it stays so, cleared when it leaves it."""

    def bulk_create(self, objs, *args, **kwargs):
        now = timezone.now()
        for obj in objs:
            if obj.state == PaymentState.DONE:
                if obj.done_date is None:
                    obj.done_date = now
            else:
                obj.done_date = None
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        now = timezone.now()
        # See `AccountQuerySet.update`.
        kwargs.setdefault("update_date", now)
        if "state" in kwargs:
            if kwargs["state"] == PaymentState.DONE:
                # In the same UPDATE: a SET expression reads the row as it was
                # before the statement, so a payment already done keeps the date
                # it was first marked so, and the others take now.
                kwargs.setdefault(
                    "done_date",
                    Case(When(state=PaymentState.DONE, then=F("done_date")), default=Value(now)),
                )
            else:
                kwargs.setdefault("done_date", None)
        return super().update(**kwargs)


class Payment(models.Model):
    """Money paid or received, by one payment method.

    The amount is positive; `direction` says which way it goes. A payment settles
    at most one document, for its whole amount (`target_type` and one foreign key
    per kind of document); several payments may settle the same one.

    A `done` payment on a document books an `AccountMovement` (`account_movement`),
    kept in step by `PaymentService`. The link lives here and not on the movement:
    `account` does not know this app, which already depends on it.
    """

    id = ULIDField("ID", primary_key=True)
    date = models.DateField("Date", db_index=True)
    amount = models.DecimalField("Amount", max_digits=19, decimal_places=2)
    currency_code = models.CharField(
        "Currency", max_length=3, choices=CurrencyCode.choices, default=CurrencyCode.EUR
    )
    direction = models.CharField("Direction", max_length=16, choices=PaymentDirection.choices)
    state = models.CharField(
        "State", max_length=16, choices=PaymentState.choices, default=PaymentState.DRAFT
    )
    done_date = models.DateTimeField(
        "Done Date", null=True, blank=True, editable=False,
        help_text="When the payment was marked done; empty while it is not.",
    )
    payment_method = models.ForeignKey(
        "payment.PaymentMethod",
        verbose_name="Payment Method",
        related_name="payments",
        on_delete=models.PROTECT,
    )
    contact = models.ForeignKey(
        "contact.Contact",
        verbose_name="Contact",
        related_name="payments",
        null=True,
        blank=True,
        # As `AccountMovement.contact`: the payment outlives its counterparty.
        on_delete=models.SET_NULL,
        help_text="Who is paid, or who pays.",
    )
    reference = models.CharField("Reference", max_length=100, null=True, blank=True)

    # The document settled: one foreign key per kind, tied to `target_type` by the
    # `payment_target` constraint. Rather than a generic foreign key: a real
    # column per kind keeps the integrity, the `on_delete` and the joins.
    target_type = models.CharField(
        "Target Type",
        max_length=16,
        choices=PaymentTargetType.choices,
        null=True,
        blank=True,
        help_text="The kind of document the payment settles; empty for none.",
    )
    invoice = models.ForeignKey(
        "account.Invoice",
        verbose_name="Invoice",
        related_name="payments",
        null=True,
        blank=True,
        # A paid invoice stays: its payments would lose what they settled.
        on_delete=models.PROTECT,
    )

    account_movement = models.OneToOneField(
        "account.AccountMovement",
        verbose_name="Account Movement",
        related_name="payment",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        help_text="The movement the payment booked, while it is done and settles a document.",
    )

    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = PaymentQuerySet.as_manager()

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payment_amount_positive",
                violation_error_message="The amount must be positive.",
            ),
            # One branch per target type, extended with each new one.
            models.CheckConstraint(
                condition=(
                    Q(target_type__isnull=True, invoice__isnull=True)
                    | Q(target_type=PaymentTargetType.INVOICE, invoice__isnull=False)
                ),
                name="payment_target",
                violation_error_message="The document of the payment does not match its target type.",
            ),
        ]

    def __str__(self):
        return self.reference or f"{self.amount} {self.currency_code}"

    def save(self, *args, **kwargs):
        # The admin writes through `save()`, not through the QuerySet.
        if self.state == PaymentState.DONE:
            if self.done_date is None:
                self.done_date = timezone.now()
        else:
            self.done_date = None
        super().save(*args, **kwargs)
