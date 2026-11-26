from typing import Optional

from pydantic import Field, field_validator

from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from payment.models import PaymentMethod
from payment.models.payment_method import compact_iban

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

PAYMENT_METHOD_FIELDS = ["sequence", "active", "name", "code", "type", "iban"]


class PaymentMethodDisplayNameSchema(ModelSchema):
    class Meta:
        model = PaymentMethod
        fields = ["id", "code", "name", "type"]


class PaymentMethodSchema(ModelSchema):
    class Meta:
        model = PaymentMethod
        fields = ["id", *PAYMENT_METHOD_FIELDS]
        optional_fields = "__all__"


class PaymentMethodCreateSchema(ModelSchema):
    class Meta:
        model = PaymentMethod
        fields = PAYMENT_METHOD_FIELDS
        # Required for a bank method only: `PaymentMethodService` says so.
        optional_fields = ["sequence", "active", "iban"]

    # Before the `max_length` of the column, which reads the electronic form: an
    # IBAN typed with its spaces is longer.
    @field_validator("iban", mode="before", check_fields=False)
    @classmethod
    def _compact_iban(cls, value):
        return compact_iban(value) if isinstance(value, str) else value


class PaymentMethodUpdateSchema(ModelSchema):
    class Meta:
        model = PaymentMethod
        fields = PAYMENT_METHOD_FIELDS
        optional_fields = "__all__"

    # See `PaymentMethodCreateSchema`.
    @field_validator("iban", mode="before", check_fields=False)
    @classmethod
    def _compact_iban(cls, value):
        return compact_iban(value) if isinstance(value, str) else value


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class PaymentMethodFilterSchema(FilterSchema):
    active: Optional[bool] = Field(
        None,
        title="Active",
        description="Only the active, or only the inactive payment methods.",
    )
    type: MultiValue(str, allow_null=False) = Field(
        None,
        q="type",
        title="Type",
        description="Comma-separated types (`cash`, `bank`).",
    )
    search: Optional[str] = Field(
        None,
        q=["code__icontains", "name__icontains", "iban__icontains"],
        title="Search Term",
        description="Search term in the code, the name or the IBAN.",
    )
