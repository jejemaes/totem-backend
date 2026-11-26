import mimetypes

from django.db.models import Q, Sum
from django.utils import timezone

from base.files.validation import validate_upload

from core.services import (
    CreateMixin,
    DeleteMixin,
    Dimension,
    GroupByMixin,
    Measure,
    ReadMixin,
    ResequenceMixin,
    ServiceBase,
    ServiceValidationError,
    ServiceValidationMultiError,
    UpdateMixin,
    date_dimensions,
    number_measures,
    share_measure,
)
from payment.choices import PaymentDirection, PaymentState, PaymentTargetType
from payment.services.mixins import PaymentTargetServiceMixin
from account.choices import MovementOriginType
from account.models import (
    Account,
    AccountCategory,
    AccountMovement,
    Budget,
    BudgetLine,
    BudgetPosition,
    Invoice,
)
from account.schemas import (
    AccountCategoryCreateSchema,
    AccountCategoryUpdateSchema,
    AccountCreateSchema,
    AccountMovementCreateSchema,
    AccountMovementUpdateSchema,
    AccountUpdateSchema,
    BudgetCreateSchema,
    BudgetLineCreateSchema,
    BudgetLineUpdateSchema,
    BudgetPositionCreateSchema,
    BudgetPositionUpdateSchema,
    BudgetUpdateSchema,
    InvoiceCreateSchema,
    InvoiceUpdateSchema,
)


class AccountService(
    CreateMixin[AccountCreateSchema],
    ReadMixin,
    UpdateMixin[AccountUpdateSchema],
    DeleteMixin,
    ServiceBase[Account],
):
    """Deleting an account with movements is refused by its `PROTECT` foreign key,
    reported as a validation error by `DeleteMixin`: deactivate it instead."""


class AccountCategoryService(
    CreateMixin[AccountCategoryCreateSchema],
    ReadMixin,
    UpdateMixin[AccountCategoryUpdateSchema],
    DeleteMixin,
    ServiceBase[AccountCategory],
):
    pass


class AccountMovementService(
    CreateMixin[AccountMovementCreateSchema],
    ReadMixin,
    GroupByMixin,
    UpdateMixin[AccountMovementUpdateSchema],
    DeleteMixin,
    ServiceBase[AccountMovement],
):
    """Every write here goes stale the stored totals of the accounts concerned,
    which the computed-field context of the write refreshes before it commits.

    Grouped by account, category, contact, origin and period. The amount is signed,
    so its sum is the balance: the debits and the credits are measures of their
    own, as there is no direction column to group by.

    A movement with an origin (`origin_type`) is booked by a payment of its
    document (`PaymentService._sync_account_movements`), which owns its amount,
    date and reference: those are refused here on update, and the movement on
    delete, so the ledger cannot disagree with what was paid. Correct the payment
    instead. The rest -- its name, description, category, contact -- is edited
    as on any movement.
    """

    group_by_dimensions = {
        "account": Dimension("account"),
        "category": Dimension("category"),
        "contact": Dimension("contact"),
        "origin_type": Dimension("origin_type"),
        **date_dimensions("date", ["day", "week", "month", "quarter", "year"]),
    }
    group_by_measures = {
        **number_measures("amount"),
        "debit_sum": Measure(Sum("amount", filter=Q(amount__lt=0)), "amount", label="Debits"),
        "credit_sum": Measure(Sum("amount", filter=Q(amount__gt=0)), "amount", label="Credits"),
        # The share of each category in its period, or in the whole when grouped by
        # category alone.
        **share_measure("amount", exclude=["category"]),
    }

    # What the document a movement was booked from owns.
    ORIGIN_OWNED_FIELDS = ("amount", "date", "reference")

    def validate_data(self, data, instance):
        error = self.ValidationError({})

        if instance is not None and instance.origin_type is not None:
            for name in self.ORIGIN_OWNED_FIELDS:
                if name in data:
                    error.add_message(
                        "This movement was booked from a document: change the document instead.",
                        key=name,
                    )
            if error:
                raise error

        # Also a check constraint, which only reports an unkeyed integrity error.
        if "amount" in data and data["amount"] == 0:
            error.add_message("The amount cannot be zero.", key="amount")

        # Policy, not schema: as a field validator it would sit in the migration.
        # Today in the timezone of the site, not in UTC.
        date = data.get("date")
        if date is not None:
            if date > timezone.localdate():
                error.add_message("The date cannot be in the future.", key="date")

        # Relations arrive resolved, as instances: comparing ids costs no query.
        category = data.get("category")
        if category is not None and category.account_id is not None:
            account_id = data["account"].pk if instance is None else instance.account_id
            if category.account_id != account_id:
                error.add_message(
                    "This category belongs to another account.", key="category"
                )

        if error:
            raise error

    def _delete_preprocess(self, queryset):
        # On the queryset about to be deleted: a single booked movement refuses
        # the whole batch, reported as a `PROTECT` would be.
        if queryset.filter(origin_type__isnull=False).exists():
            raise ServiceValidationMultiError(
                {"__all__": ServiceValidationError(
                    "A movement booked from a document cannot be deleted: change the document instead."
                )},
                code="protected_error",
            )
        return queryset


class InvoiceService(
    PaymentTargetServiceMixin,
    CreateMixin[InvoiceCreateSchema],
    ReadMixin,
    GroupByMixin,
    UpdateMixin[InvoiceUpdateSchema],
    DeleteMixin,
    ServiceBase[Invoice],
):
    """`number` is assigned by `InvoiceQuerySet.bulk_create`; `file_mimetype` is
    derived from the uploaded file by `_create_preprocess_values`, as for a
    document. The paid amounts follow the payments targeting the invoice.

    The payments of an invoice are registered, changed and deleted from here
    (`PaymentTargetServiceMixin`), and their rules are those of a supplier
    invoice: paid by outgoing payments in its currency, never beyond what is due.

    Deleting an invoice with payments or movements is refused by their `PROTECT`
    foreign keys, reported as a validation error.
    """

    # A scanned invoice can be a large PDF, as a document.
    MAX_UPLOAD_SIZE = 20 * 1024 * 1024

    group_by_dimensions = {
        "account": Dimension("account"),
        "category": Dimension("category"),
        "contact": Dimension("contact"),
        "payment_status": Dimension("payment_status"),
        "currency_code": Dimension("currency_code"),
        **date_dimensions("date", ["month", "quarter", "year"]),
    }
    group_by_measures = {
        **number_measures("amount_total", ["sum"]),
        **number_measures("amount_paid", ["sum"]),
        **number_measures("amount_residual", ["sum"]),
    }

    def validate_data(self, data, instance):
        error = self.ValidationError({})

        if "amount_total" in data and data["amount_total"] is not None and data["amount_total"] <= 0:
            error.add_message("The total amount must be positive.", key="amount_total")

        # Policy, as for a movement: today in the timezone of the site.
        date = data.get("date")
        if date is not None and date > timezone.localdate():
            error.add_message("The date cannot be in the future.", key="date")

        # The rule of the movements its payments book, which take this category:
        # one of another account would be refused there. Checked when either
        # side changes, the other one read from the invoice.
        if "category" in data or "account" in data:
            if "category" in data:
                category = data["category"]
            else:
                # Only when the account changes under a category: one query then.
                category = instance.category if instance is not None and instance.category_id else None
            # A null account is refused by the field itself.
            account_id = getattr(data["account"], "pk", None) if "account" in data else instance.account_id
            if category is not None and category.account_id is not None and category.account_id != account_id:
                error.add_message("This category belongs to another account.", key="category")

        upload = data.get("file_content")
        if instance is None and upload is not None:
            try:
                validate_upload(upload, self.MAX_UPLOAD_SIZE, key="file_content")
                # Narrower than the floor of `validate_upload`: what a viewer of
                # invoices can show.
                mimetype = mimetypes.guess_type(upload.name or "")[0] or ""
                if mimetype != "application/pdf" and not mimetype.startswith("image/"):
                    raise self.ValidationError("The file must be a PDF or an image.", key="file_content")
            except self.ValidationError as exc:
                for key, messages in exc.message_dict.items():
                    error.add_message(messages, key=key)

        if error:
            raise error

    # Payments

    payment_target_type = PaymentTargetType.INVOICE
    payment_target_field = "invoice"

    @classmethod
    def _payment_default_values(cls, target):
        # A supplier invoice: we pay it, in its currency, to its supplier.
        return {
            "direction": PaymentDirection.OUTGOING,
            "currency_code": target.currency_code,
            "contact": target.contact_id,
        }

    @classmethod
    def _payment_validate(cls, target, values, instance):
        error = cls.ValidationError({})
        if values["direction"] != PaymentDirection.OUTGOING:
            error.add_message("An invoice is paid by an outgoing payment.", key="direction")
        if values["currency_code"] != target.currency_code:
            error.add_message(
                f"The invoice is in {target.currency_code}, the payment in {values['currency_code']}.",
                key="currency_code",
            )
        # A done payment cannot pay more than what is due. Its own share, if it
        # already counted towards the invoice, is due again once rewritten.
        amount = values["amount"]
        if values["state"] == PaymentState.DONE and amount is not None and target.amount_residual is not None:
            due = target.amount_residual
            if (
                instance is not None
                and instance.state == PaymentState.DONE
                and instance.invoice_id == target.pk
            ):
                due += instance.amount
            if amount > due:
                error.add_message(f"The amount exceeds what is due on the invoice ({due}).", key="amount")
        if error:
            raise error

    @classmethod
    def _payment_movement_values(cls, target, payment):
        return {
            "account_id": target.account_id,
            "reference": target.number,
            "contact_id": payment.contact_id or target.contact_id,
            # The default: the movement's own once booked, see
            # `PaymentService.movement_initial_fields`.
            "category_id": target.category_id,
            "origin_type": MovementOriginType.INVOICE,
            "invoice_id": target.pk,
        }

    def _create_preprocess_values(self, internal_data):
        for values in internal_data:
            upload = values.get("file_content")
            if upload is not None:
                # From the filename, as `validate_upload` checked it.
                values["file_mimetype"] = mimetypes.guess_type(upload.name or "")[0]
        return internal_data


class BudgetService(
    CreateMixin[BudgetCreateSchema],
    ReadMixin,
    UpdateMixin[BudgetUpdateSchema],
    DeleteMixin,
    ServiceBase[Budget],
):

    async def _default_values(self, fields=None):
        """A budget whose user is not given is the acting user's.

        Here rather than on the model, which knows no acting user; and `create`
        fills from it only the fields an input leaves out, so a user explicitly set
        to null stays null. Resolved afterwards through the user service like any
        relation, so it is checked the same way. Without it, a user whose access
        rule only reaches their own budgets could not create one without naming
        themselves.
        """
        values = await super()._default_values(fields)
        if self.user is not None and (fields is None or "user" in fields):
            values["user"] = self.user.pk
        return values


class BudgetPositionService(
    CreateMixin[BudgetPositionCreateSchema],
    ReadMixin,
    GroupByMixin,
    UpdateMixin[BudgetPositionUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[BudgetPosition],
):
    """Grouped by category, with the planned and practical totals of the positions.

    A budget has one position per category at most, so within one budget a group
    is one position: the aggregates only add up across budgets.
    """

    group_by_dimensions = {"category": Dimension("category")}
    group_by_measures = {
        **number_measures("total_planned", ["sum", "avg"]),
        **number_measures("total_practical", ["sum", "avg"]),
    }

    def validate_data(self, data, instance):
        # The rule of the movements: a position on a category of another account
        # could never read a practical amount, no movement of the budget's account
        # can carry it.
        category = data.get("category")
        if category is None or category.account_id is None:
            return
        account_id = data["budget"].account_id if instance is None else instance.budget.account_id
        if category.account_id != account_id:
            raise self.ValidationError(
                "This category belongs to another account than the budget's.", key="category"
            )


class BudgetLineService(
    CreateMixin[BudgetLineCreateSchema],
    ReadMixin,
    UpdateMixin[BudgetLineUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[BudgetLine],
):
    """`budget` is derived from the position by the QuerySet. It is still part of the
    create schema, so that a caller naming a budget -- the nested API route does --
    gets an error rather than a line silently filed under another one."""

    def validate_data(self, data, instance):
        position = data.get("position")
        if position is None:
            return
        budget_id = data["budget"].pk if instance is None else instance.budget_id
        if position.budget_id != budget_id:
            raise self.ValidationError(
                "This position belongs to another budget.", key="position"
            )
