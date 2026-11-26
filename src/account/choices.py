from django.db import models


class MovementOriginType(models.TextChoices):
    """The kind of document a movement was booked from. One foreign key per kind
    on `AccountMovement`, which the `account_movement_origin` constraint ties to
    this value."""

    INVOICE = "invoice", "Invoice"
