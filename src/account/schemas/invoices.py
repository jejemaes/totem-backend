"""Schemas for `account.Invoice`.

`InvoiceCreateSchema` carries an actual uploaded file, as `DocumentCreateSchema`:
the controller accepts `multipart/form-data` and declares the file as a
parameter of its own.
"""

from datetime import date
from typing import Optional

from ninja.files import UploadedFile
from pydantic import Field, field_validator

from contact.schemas import ContactDisplayNameSchema
from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from account.models import Invoice

from .account_categories import AccountCategoryDisplayNameSchema
from .accounts import AccountDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

INVOICE_FIELDS = ["name", "reference", "date", "due_date", "contact", "account", "category", "description", "amount_total", "currency_code"]


class InvoiceDisplayNameSchema(ModelSchema):
    class Meta:
        model = Invoice
        fields = ["id", "number", "name", "reference"]


class InvoiceSchema(ModelSchema):
    contact: Optional[ContactDisplayNameSchema] = None
    account: Optional[AccountDisplayNameSchema] = None
    category: Optional[AccountCategoryDisplayNameSchema] = None

    class Meta:
        model = Invoice
        fields = [
            "id",
            "number",
            *INVOICE_FIELDS,
            "file_content",
            "file_mimetype",
            "amount_paid",
            "amount_residual",
            "payment_status",
            "create_date",
            "update_date",
        ]
        optional_fields = "__all__"

    # See `DocumentSchema._stored_path_to_url`: a list serializes the bare stored
    # path, a retrieve the `.url` of the `FieldFile`.
    @field_validator("file_content", mode="before", check_fields=False)
    @classmethod
    def _stored_path_to_url(cls, value, info):
        if value == "":
            return None
        if isinstance(value, str) and not value.startswith("/"):
            return Invoice._meta.get_field(info.field_name).storage.url(value)
        return value


class InvoiceCreateSchema(ModelSchema):
    # The generated field would be a `str`, which cannot carry bytes; see
    # `MediaCreateSchema.content`.
    file_content: Optional[UploadedFile] = None

    class Meta:
        model = Invoice
        fields = [*INVOICE_FIELDS, "file_content"]
        optional_fields = ["name", "reference", "due_date", "category", "description", "currency_code", "file_content"]


class InvoiceCreateFormSchema(ModelSchema):
    """The form fields of a creation, sent as `multipart/form-data` beside the
    `file_content` part: `InvoiceCreateSchema` without the file (see
    `InvoiceController`)."""

    class Meta:
        model = Invoice
        fields = INVOICE_FIELDS
        optional_fields = ["name", "reference", "due_date", "category", "description", "currency_code"]


class InvoiceUpdateSchema(ModelSchema):
    class Meta:
        model = Invoice
        fields = INVOICE_FIELDS
        optional_fields = "__all__"


# No `number` in any write schema: assigned at creation. No `file_content` in the
# update schema: `queryset.update()` skips `FileField.pre_save`, so a new file
# would never reach the storage. `file_mimetype` and the paid amounts are in no
# write schema: derived.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class InvoiceFilterSchema(FilterSchema):
    contact: MultiValue(str, allow_null=False) = Field(
        None,
        q="contact__id",
        title="Contact",
        description="Comma-separated identifiers of the suppliers.",
    )
    account: MultiValue(str, allow_null=False) = Field(
        None,
        q="account__id",
        title="Account",
        description="Comma-separated identifiers of the accounts.",
    )
    category: MultiValue(str) = Field(
        None,
        q="category__id",
        title="Default Category",
        description="Comma-separated identifiers of the categories, `null` for the invoices without one.",
    )
    payment_status: MultiValue(str, allow_null=False) = Field(
        None,
        q="payment_status",
        title="Payment Status",
        description="Comma-separated payment statuses (`not_paid`, `partially_paid`, `paid`).",
    )
    date_from: Optional[date] = Field(
        None,
        q="date__gte",
        title="From",
        description="Invoices on or after this date.",
    )
    date_to: Optional[date] = Field(
        None,
        q="date__lte",
        title="To",
        description="Invoices on or before this date.",
    )
    search: Optional[str] = Field(
        None,
        q=["number__icontains", "name__icontains", "reference__icontains"],
        title="Search Term",
        description="Search term in the number, the name or the reference.",
    )
