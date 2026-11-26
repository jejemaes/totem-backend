from django.db import models


class InvoicePaymentStatus(models.TextChoices):
    NOT_PAID = "not_paid", "Not Paid"
    PARTIALLY_PAID = "partially_paid", "Partially Paid"
    PAID = "paid", "Paid"


class MovementOriginType(models.TextChoices):
    """The kind of document a movement was booked from. One foreign key per kind
    on `AccountMovement`, which the `account_movement_origin` constraint ties to
    this value."""

    INVOICE = "invoice", "Invoice"
