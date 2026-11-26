from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from stdnum import iban as stdnum_iban
from stdnum.exceptions import (
    InvalidChecksum,
    InvalidComponent,
    InvalidLength,
    ValidationError as StdnumValidationError,
)

from core.orm.fields import ULIDField
from payment.choices import PaymentMethodType

PAYMENT_METHOD_CODE_PATTERN = r"^[A-Z0-9_-]{1,50}$"
# The electronic form of an IBAN, the one stored: a country, two check digits, the
# bank account; upper case, no space.
IBAN_PATTERN = r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$"


def compact_iban(value):
    """The electronic form of an IBAN as typed, with spaces or in lower case;
    None for a blank one. Whatever it is: `validate_iban` judges it."""
    if value is None or not value.strip():
        return None
    return stdnum_iban.compact(value)


def validate_iban(value):
    """ISO 13616: a known country, its length, the mod-97 check digits, and the
    national bank account of the countries `python-stdnum` knows (the RIB key of a
    French one). Any formatting: the IBAN is judged in its electronic form, which
    `compact_iban` stores. Rather than written here: the length of each country is
    a table to maintain, which the library does."""
    try:
        stdnum_iban.validate(value)
    except InvalidChecksum:
        raise ValidationError("The check digits of this IBAN are wrong.", code="invalid_iban")
    except InvalidLength:
        raise ValidationError("This IBAN does not have the length of its country.", code="invalid_iban")
    except InvalidComponent:
        raise ValidationError("This IBAN has an unknown country or an invalid bank account.", code="invalid_iban")
    except StdnumValidationError:
        raise ValidationError("This is not an IBAN.", code="invalid_iban")


class PaymentMethodQuerySet(models.QuerySet):
    """Stores the IBAN in its electronic form whoever writes it, as
    `payment_method_iban_format` requires."""

    def bulk_create(self, objs, *args, **kwargs):
        for obj in objs:
            obj.iban = compact_iban(obj.iban)
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        if "iban" in kwargs:
            kwargs["iban"] = compact_iban(kwargs["iban"])
        return super().update(**kwargs)


class PaymentMethod(models.Model):
    id = ULIDField("ID", primary_key=True)
    sequence = models.IntegerField("Sequence", default=10)
    # `active` rather than `is_active`: the name of the flag on every other model
    # of the project (`Account.active`, `Budget.active`).
    active = models.BooleanField("Active", default=True)
    name = models.CharField("Name", max_length=255)
    code = models.CharField(
        "Code",
        max_length=50,
        # As `Account.code`: the pattern lands in the request schemas, the check
        # constraint covers the ORM side.
        validators=[RegexValidator(PAYMENT_METHOD_CODE_PATTERN)],
        help_text="Upper case letters, digits, '_' and '-' only.",
    )
    type = models.CharField("Type", max_length=16, choices=PaymentMethodType.choices)
    iban = models.CharField(
        "IBAN",
        max_length=34,
        null=True,
        blank=True,
        validators=[validate_iban],
        help_text="The bank account, required for a bank method and only there. Stored upper case, without spaces.",
    )

    objects = PaymentMethodQuerySet.as_manager()

    class Meta:
        verbose_name = "Payment Method"
        verbose_name_plural = "Payment Methods"
        constraints = [
            # Named rather than `unique=True`, as `Account.code`.
            models.UniqueConstraint(
                fields=["code"],
                name="unique_payment_method_code",
                violation_error_message="A payment method with that code already exists.",
            ),
            models.CheckConstraint(
                condition=Q(code__regex=PAYMENT_METHOD_CODE_PATTERN),
                name="payment_method_code_format",
                violation_error_message="The code may only contain upper case letters, digits, '_' and '-'.",
            ),
            models.CheckConstraint(
                condition=Q(iban__isnull=True) | Q(iban__regex=IBAN_PATTERN),
                name="payment_method_iban_format",
                violation_error_message="The IBAN must be stored upper case, without spaces.",
            ),
            models.CheckConstraint(
                condition=Q(type=PaymentMethodType.BANK, iban__isnull=False)
                | (~Q(type=PaymentMethodType.BANK) & Q(iban__isnull=True)),
                name="payment_method_iban_bank",
                violation_error_message="A bank payment method has an IBAN, and only a bank one.",
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # The admin writes through `save()`, not through the QuerySet.
        self.iban = compact_iban(self.iban)
        super().save(*args, **kwargs)
