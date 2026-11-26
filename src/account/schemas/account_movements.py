from datetime import date
from typing import Literal, Optional

from django.db.models import Q
from pydantic import Field

from contact.schemas import ContactDisplayNameSchema
from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from account.models import AccountMovement

from .account_categories import AccountCategoryDisplayNameSchema
from .accounts import AccountDisplayNameSchema
from .invoices import InvoiceDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------

MOVEMENT_FIELDS = ["amount", "name", "description", "date", "reference", "category", "contact"]


class AccountMovementDisplayNameSchema(ModelSchema):
    class Meta:
        model = AccountMovement
        fields = ["id", "name", "amount", "date"]


class AccountMovementSchema(ModelSchema):
    account: Optional[AccountDisplayNameSchema] = None
    category: Optional[AccountCategoryDisplayNameSchema] = None
    contact: Optional[ContactDisplayNameSchema] = None
    invoice: Optional[InvoiceDisplayNameSchema] = None

    class Meta:
        model = AccountMovement
        fields = ["id", "account", *MOVEMENT_FIELDS, "origin_type", "invoice", "create_date", "update_date"]
        optional_fields = "__all__"


class AccountMovementCreateSchema(ModelSchema):
    class Meta:
        model = AccountMovement
        fields = ["account", *MOVEMENT_FIELDS]
        optional_fields = ["description", "reference", "category", "contact"]


class AccountMovementUpdateSchema(ModelSchema):
    class Meta:
        model = AccountMovement
        fields = MOVEMENT_FIELDS
        optional_fields = "__all__"


# No `account` in the update schema: moving a movement to another account would
# move money between their balances behind a correction of a line, and would have
# to re-check the scope of its category. Delete it and create it on the right one.
# No `origin_type` nor `invoice` in any write schema: a movement with an origin is
# booked by its document, never by hand.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class AccountMovementFilterSchema(FilterSchema):
    account: MultiValue(str, allow_null=False) = Field(
        None,
        q="account__id",
        title="Account",
        description="Comma-separated identifiers of the accounts.",
    )
    category: MultiValue(str) = Field(
        None,
        q="category__id",
        title="Category",
        description="Comma-separated identifiers of the categories, `null` for the "
        "uncategorized movements.",
    )
    contact: MultiValue(str) = Field(
        None,
        q="contact__id",
        title="Contact",
        description="Comma-separated identifiers of the contacts, `null` for the "
        "movements without counterparty.",
    )
    origin_type: MultiValue(str) = Field(
        None,
        q="origin_type",
        title="Origin Type",
        description="Comma-separated origin types (`invoice`), `null` for the "
        "movements entered by hand.",
    )
    invoice: MultiValue(str) = Field(
        None,
        q="invoice__id",
        title="Invoice",
        description="Comma-separated identifiers of the invoices the movements were booked from.",
    )
    date_from: Optional[date] = Field(
        None,
        q="date__gte",
        title="From",
        description="Movements on or after this date.",
    )
    date_to: Optional[date] = Field(
        None,
        q="date__lte",
        title="To",
        description="Movements on or before this date.",
    )
    direction: Optional[Literal["debit", "credit"]] = Field(
        None,
        title="Direction",
        description="`debit` for the expenses (negative amounts), `credit` for the "
        "revenues (positive amounts).",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains", "reference__icontains"],
        title="Search Term",
        description="Search term in the name or the reference.",
    )

    def filter_direction(self, value):
        # The sign of the amount is the direction: there is no column for it.
        if value == "debit":
            return Q(amount__lt=0)
        if value == "credit":
            return Q(amount__gt=0)
        return Q()
