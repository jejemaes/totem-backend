from django.db import models
from django.utils import timezone

from account.choices import MovementOriginType
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
    contact = models.ForeignKey(
        "contact.Contact",
        verbose_name="Contact",
        # Not `movements`: seen from a contact, the name must say which ones.
        related_name="account_movements",
        null=True,
        blank=True,
        # The movement outlives its counterparty: the ledger keeps its amounts.
        on_delete=models.SET_NULL,
        help_text="Counterparty of the movement (a supplier, a customer...).",
    )
    # The document a movement was booked from: one foreign key per kind, which the
    # `account_movement_origin` constraint ties to `origin_type`. Rather than a
    # generic foreign key: a real column per kind keeps the integrity, the
    # `on_delete` and the joins. Both empty for a movement entered by hand.
    origin_type = models.CharField(
        "Origin Type",
        max_length=16,
        choices=MovementOriginType.choices,
        null=True,
        blank=True,
        help_text="The kind of document the movement was booked from; empty when entered by hand.",
    )
    invoice = models.ForeignKey(
        "account.Invoice",
        verbose_name="Invoice",
        related_name="account_movements",
        null=True,
        blank=True,
        # The ledger keeps what was paid: an invoice with movements stays.
        on_delete=models.PROTECT,
        help_text="The invoice whose payment booked the movement.",
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
            # One branch per origin type, extended with each new one.
            models.CheckConstraint(
                condition=(
                    models.Q(origin_type__isnull=True, invoice__isnull=True)
                    | models.Q(origin_type=MovementOriginType.INVOICE, invoice__isnull=False)
                ),
                name="account_movement_origin",
                violation_error_message="The origin of the movement does not match its origin type.",
            ),
        ]

    def __str__(self):
        return self.name
