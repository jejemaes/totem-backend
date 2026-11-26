from django.db import models


class FileReferencePrivacy(models.TextChoices):
    PUBLIC = 'public', 'Public'
    PRIVATE = 'private', 'Private'


class CurrencyCode(models.TextChoices):
    """ISO 4217 codes of the currencies an amount may be expressed in."""

    EUR = "EUR", "Euro"
    USD = "USD", "US Dollar"
