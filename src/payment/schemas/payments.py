from datetime import date
from typing import Optional

from pydantic import Field

from account.models import AccountMovement
from contact.schemas import ContactDisplayNameSchema
from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from payment.models import Payment

from .payment_methods import PaymentMethodDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

# What a payment is, whatever it settles.
PAYMENT_FIELDS = [
    "date",
    "amount",
    "currency_code",
    "direction",
    "state",
    "payment_method",
    "contact",
    "reference",
]
# What the routes of a document read and write of its payments: they are all
# `done` and paid to the document's contact, so neither `state` nor `contact`.
DOCUMENT_PAYMENT_FIELDS = ["date", "amount", "currency_code", "direction", "payment_method", "reference"]
# What it settles: the target type, and one foreign key per type.
PAYMENT_TARGET_FIELDS = ["target_type", "invoice"]


class PaymentAccountMovementSchema(ModelSchema):
    """The movement a payment booked. Its own schema rather than one of
    `account.schemas`, which imports this app's to register the payments of an
    invoice: the import would go round."""

    class Meta:
        model = AccountMovement
        fields = ["id", "name", "amount", "date"]


class PaymentInvoiceTargetSchema(ModelSchema):
    """The invoice a payment settles, as `InvoiceDisplayNameSchema` reads it --
    the same fields, which `account` tests. Declared here rather than imported:
    `account.schemas` imports this app's to register the payments of an invoice,
    so the import would go round. Only the model its foreign key points at is
    known here."""

    class Meta:
        model = Payment._meta.get_field("invoice").related_model
        fields = ["id", "number", "name", "reference"]


class PaymentSchema(ModelSchema):
    payment_method: Optional[PaymentMethodDisplayNameSchema] = None
    contact: Optional[ContactDisplayNameSchema] = None
    account_movement: Optional[PaymentAccountMovementSchema] = None
    # The document settled, as its display name. A schema rather than a bare pk,
    # so that the response loads it, instead of fetching it from a coroutine.
    invoice: Optional[PaymentInvoiceTargetSchema] = None

    class Meta:
        model = Payment
        fields = [
            "id", *PAYMENT_FIELDS, *PAYMENT_TARGET_FIELDS, "done_date", "account_movement",
            "create_date", "update_date",
        ]
        optional_fields = "__all__"


class PaymentOfDocumentSchema(ModelSchema):
    """A payment as the routes of the document it settles read it: without its
    target, which is the document of the path, nor its state and contact, which
    are those of every payment of a document (see `DOCUMENT_PAYMENT_FIELDS`). A
    document's controller may subclass it, for a schema of its own name."""

    payment_method: Optional[PaymentMethodDisplayNameSchema] = None
    account_movement: Optional[PaymentAccountMovementSchema] = None

    class Meta:
        model = Payment
        fields = ["id", *DOCUMENT_PAYMENT_FIELDS, "done_date", "account_movement", "create_date", "update_date"]
        optional_fields = "__all__"


class PaymentCreateSchema(ModelSchema):
    """The input of `PaymentService.create`, target included: the body of
    `POST /payment/payments/`, and what `PaymentTargetServiceMixin.payment_register`
    builds."""

    class Meta:
        model = Payment
        fields = [*PAYMENT_FIELDS, *PAYMENT_TARGET_FIELDS]
        optional_fields = ["currency_code", "direction", "state", "contact", "reference", *PAYMENT_TARGET_FIELDS]


class PaymentUpdateSchema(ModelSchema):
    """The input of `PaymentService.update`, the body of
    `PATCH /payment/payments/{id}/`; see `PaymentCreateSchema`."""

    class Meta:
        model = Payment
        fields = [*PAYMENT_FIELDS, *PAYMENT_TARGET_FIELDS]
        optional_fields = "__all__"


class PaymentRegisterSchema(ModelSchema):
    """The body registering a payment of a document: neither the target, which
    the route forces, nor the state -- registered `done` -- nor the contact --
    the document's. A document's controller may subclass it, for a schema of its
    own name. `direction` and `currency_code` are optional: the document gives
    their defaults."""

    class Meta:
        model = Payment
        fields = DOCUMENT_PAYMENT_FIELDS
        optional_fields = ["currency_code", "direction", "reference"]


class PaymentChangeSchema(ModelSchema):
    """The body changing a payment of a document; see `PaymentRegisterSchema`.
    The target cannot change: delete the payment and register another."""

    class Meta:
        model = Payment
        fields = DOCUMENT_PAYMENT_FIELDS
        optional_fields = "__all__"


# `done_date` and `account_movement` are in no write schema: the first follows
# `state` (`PaymentQuerySet`), the second is booked by `PaymentService`.
# No display name schema: nothing relates to a payment.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class PaymentFilterSchema(FilterSchema):
    state: MultiValue(str, allow_null=False) = Field(
        None,
        q="state",
        title="State",
        description="Comma-separated states (`draft`, `pending`, `cancelled`, `done`).",
    )
    direction: Optional[str] = Field(
        None,
        q="direction",
        title="Direction",
        description="`incoming` or `outgoing`.",
    )
    payment_method: MultiValue(str, allow_null=False) = Field(
        None,
        q="payment_method__id",
        title="Payment Method",
        description="Comma-separated identifiers of the payment methods.",
    )
    contact: MultiValue(str) = Field(
        None,
        q="contact__id",
        title="Contact",
        description="Comma-separated identifiers of the contacts, `null` for the payments without one.",
    )
    target_type: MultiValue(str) = Field(
        None,
        q="target_type",
        title="Target Type",
        description="Comma-separated target types (`invoice`), `null` for the payments settling no document.",
    )
    invoice: MultiValue(str, allow_null=False) = Field(
        None,
        q="invoice__id",
        title="Invoice",
        description="Comma-separated identifiers of the invoices settled.",
    )
    date_from: Optional[date] = Field(
        None,
        q="date__gte",
        title="From",
        description="Payments on or after this date.",
    )
    date_to: Optional[date] = Field(
        None,
        q="date__lte",
        title="To",
        description="Payments on or before this date.",
    )
    search: Optional[str] = Field(
        None,
        q=["reference__icontains"],
        title="Search Term",
        description="Search term in the reference.",
    )
