from django.db import models


class PaymentMethodType(models.TextChoices):
    CASH = "cash", "Cash"
    BANK = "bank", "Bank"


class PaymentState(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending"
    CANCELLED = "cancelled", "Cancelled"
    DONE = "done", "Done"


class PaymentDirection(models.TextChoices):
    INCOMING = "incoming", "Incoming"
    OUTGOING = "outgoing", "Outgoing"


class PaymentTargetType(models.TextChoices):
    """The kind of document a payment settles. One foreign key per kind on
    `Payment`, which the `payment_target` constraint ties to this value; an order
    and a receipt will join the invoice."""

    INVOICE = "invoice", "Invoice"
