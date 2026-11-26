from collections import defaultdict

from django.db import connection, models, transaction
from django.db.models import Q
from django.utils import timezone

from base.choices import CurrencyCode
from base.files.storages import PrivateMediaFileSystemStorage
from base.models.mixins import CleanupFileModelMixin, CleanupFileQuerysetMixin
from core.orm.fields import ULIDField

INVOICE_NUMBER_PREFIX = "INV"
# Any constant: the key of the advisory lock serializing the numbering.
INVOICE_NUMBER_LOCK = 0x494E56  # "INV"


def assign_invoice_numbers(invoices):
    """Give the invoices without one the next numbers of the year of their date:
    `INV/2026/00001`, `INV/2026/00002`...

    Under a transaction-level advisory lock, so two concurrent creations cannot
    read the same last number; the caller holds a transaction, and the lock is
    released with it. A lock rather than a database sequence: the counter
    restarts every year, and a sequence per year would have to be created on
    the fly. The unique constraint on `number` stays the guard.
    """
    pending = [i for i in invoices if not i.number]
    if not pending:
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [INVOICE_NUMBER_LOCK])

    by_year = defaultdict(list)
    date_field = Invoice._meta.get_field("date")
    for invoice in pending:
        # `to_python`: an instance built from input may still hold the string
        # the ORM would only parse on INSERT.
        by_year[date_field.to_python(invoice.date).year].append(invoice)
    for year, year_invoices in by_year.items():
        prefix = f"{INVOICE_NUMBER_PREFIX}/{year}/"
        # Zero-padded, so the greatest string is the greatest number.
        last = (
            Invoice.objects.filter(number__startswith=prefix)
            .order_by("-number")
            .values_list("number", flat=True)
            .first()
        )
        sequence = int(last.removeprefix(prefix)) if last else 0
        for invoice in year_invoices:
            sequence += 1
            invoice.number = f"{prefix}{sequence:05d}"


class InvoiceQuerySet(CleanupFileQuerysetMixin, models.QuerySet):

    def bulk_create(self, objs, *args, **kwargs):
        # Here rather than in the service: the number must be unique whoever
        # creates the invoice. Atomic, so the lock lasts until the INSERT.
        with transaction.atomic(using=self.db):
            assign_invoice_numbers(objs)
            return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        # See `AccountQuerySet.update`.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class Invoice(CleanupFileModelMixin, models.Model):
    """A supplier invoice: what we owe a contact, to be paid from one of our
    accounts.

    The file is the original document, set at creation only: `queryset.update()`
    does not go through `FileField.pre_save`, so an update could not store a new
    one.
    """

    id = ULIDField("ID", primary_key=True)
    number = models.CharField(
        "Number",
        max_length=32,
        editable=False,
        help_text="Internal number, assigned at creation: INV/<year>/<sequence>.",
    )
    name = models.CharField(
        "Name", max_length=255, null=True, blank=True,
        help_text="A label of the user's own, describing the invoice.",
    )
    reference = models.CharField(
        "Reference", max_length=100, null=True, blank=True,
        help_text="The number the supplier gave the invoice.",
    )
    date = models.DateField("Date", db_index=True)
    due_date = models.DateField("Due Date", null=True, blank=True)
    contact = models.ForeignKey(
        "contact.Contact",
        verbose_name="Contact",
        related_name="invoices",
        # Not `SET_NULL` as on a movement: an invoice without its supplier
        # means nothing.
        on_delete=models.PROTECT,
        help_text="The supplier who issued the invoice.",
    )
    account = models.ForeignKey(
        "account.Account",
        verbose_name="Account",
        related_name="invoices",
        on_delete=models.PROTECT,
        help_text="The account its payments are booked on.",
    )
    category = models.ForeignKey(
        "account.AccountCategory",
        verbose_name="Default Category",
        related_name="invoices",
        null=True,
        blank=True,
        # As on a movement: a deleted category leaves the invoice uncategorized.
        on_delete=models.SET_NULL,
        help_text="The category of the movements its payments book; editable on each movement.",
    )
    description = models.TextField("Description", null=True, blank=True)
    amount_total = models.DecimalField("Total Amount", max_digits=19, decimal_places=2)
    currency_code = models.CharField(
        "Currency", max_length=3, choices=CurrencyCode.choices, default=CurrencyCode.EUR
    )
    file_content = models.FileField(
        "File",
        # Private: served through a signed URL, as `Document.file`.
        storage=PrivateMediaFileSystemStorage(),
        upload_to="account/invoice/%Y/%m",
        max_length=256,
        null=True,
        blank=True,
        help_text="The original document, a PDF or an image.",
    )
    file_mimetype = models.CharField(
        "File Mimetype", max_length=64, null=True, blank=True, editable=False,
        help_text="Guessed from the name of the uploaded file, for the viewer to pick.",
    )

    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"
        constraints = [
            # Named rather than `unique=True`, as `Account.code`.
            models.UniqueConstraint(
                fields=["number"],
                name="unique_invoice_number",
                violation_error_message="An invoice with that number already exists.",
            ),
            models.CheckConstraint(
                condition=Q(amount_total__gt=0),
                name="invoice_amount_total_positive",
                violation_error_message="The total amount must be positive.",
            ),
        ]

    def __str__(self):
        return self.number or "#"

    def save(self, *args, **kwargs):
        # The admin writes through `save()`, not through the QuerySet.
        with transaction.atomic():
            if self._state.adding:
                assign_invoice_numbers([self])
            super().save(*args, **kwargs)
