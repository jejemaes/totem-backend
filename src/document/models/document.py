from django.db import models
from django.utils import timezone

from base.files.storages import PrivateMediaFileSystemStorage
from base.models.mixins import CleanupFileModelMixin, CleanupFileQuerysetMixin
from core.orm.fields import HtmlField, ULIDField
from document.choices import DocumentType


def text_size(text):
    """The size of an HTML content, in bytes: what it weighs encoded in UTF-8."""
    return len((text or "").encode("utf-8"))


# "No file", whichever way it is stored: `''` by any write through the model,
# NULL only if written so explicitly.
NO_FILE = models.Q(file="") | models.Q(file__isnull=True)


class DocumentQuerySet(CleanupFileQuerysetMixin, models.QuerySet):

    def update(self, **kwargs):
        # `auto_now` only runs on `Model.save()` and on inserts, while the
        # services update through `queryset.update()`: as `PageQuerySet.update`.
        kwargs.setdefault("update_date", timezone.now())
        # The text is the only content that changes after creation, so it is
        # the only one `size` has to follow. Here rather than in the service,
        # so no writer can leave the size of a text stale.
        if "text_content" in kwargs:
            kwargs.setdefault("size", text_size(kwargs["text_content"]))
        return super().update(**kwargs)

    # No `bulk_create` override, unlike `MediaQuerySet`: the values derived at
    # creation are computed by `DocumentService._create_preprocess_values`, and
    # the admin cannot create a document (see `DocumentAdmin`).


class Document(CleanupFileModelMixin, models.Model):
    """A file uploaded, or an HTML text written in the app, sorted by tags.

    The content is fixed by `document_type`: a `file` document holds a file and
    no text, a `text` one no file. The type and the file never change after
    creation, which keeps `mimetype`, `checksum` and `size` true to the file.
    """

    id = ULIDField("ID", primary_key=True)
    name = models.CharField(
        "Name", max_length=256, help_text="For a file, the name of the uploaded file by default."
    )
    document_type = models.CharField(
        "Type", max_length=16, choices=DocumentType.choices
    )
    file = models.FileField(
        "File",
        # Private: served through a signed URL, as `User.avatar`.
        storage=PrivateMediaFileSystemStorage(),
        upload_to="document/%Y/%m",
        max_length=256,
        # `null=True` so a creation may pass `None` for "no file" (a text):
        # `to_internal_values` refuses a None into a NOT NULL column. The column
        # still holds `''` then, not NULL: `FileField.get_prep_value` turns the
        # nameless `FieldFile` into `str(value)`. Hence `NO_FILE` below.
        null=True,
        blank=True,
    )
    text_content = HtmlField("Content", null=True, blank=True, help_text="HTML content of a text document.")
    mimetype = models.CharField(
        "Mimetype", max_length=64, null=True, blank=True,
        help_text="Guessed from the name of the uploaded file; text/html for a text.",
    )
    checksum = models.CharField(
        "Checksum", max_length=128, null=True, blank=True, help_text="SHA1 of the binary data of the file."
    )
    size = models.PositiveBigIntegerField(
        "Size", default=0, help_text="In bytes: of the file, or of the text encoded in UTF-8."
    )
    date = models.DateField(
        "Date", null=True, blank=True, help_text="Date of the document itself (an invoice date...), not of its upload."
    )
    user = models.ForeignKey(
        "user.User",
        verbose_name="Owner",
        related_name="documents",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="User in charge of the document.",
    )
    contact = models.ForeignKey(
        "contact.Contact",
        verbose_name="Contact",
        related_name="documents",
        null=True,
        blank=True,
        # The document outlives the contact it was filed under.
        on_delete=models.SET_NULL,
        help_text="Contact the document is about (a supplier, a customer...).",
    )
    tags = models.ManyToManyField(
        "document.DocumentTag", verbose_name="Tags", related_name="documents", blank=True
    )
    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        verbose_name = "Document"
        verbose_name_plural = "Documents"
        constraints = [
            # A constraint rather than a service check only, so it holds for the
            # admin too.
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(document_type=DocumentType.FILE, text_content__isnull=True)
                        & ~NO_FILE
                    )
                    | (models.Q(document_type=DocumentType.TEXT) & NO_FILE)
                ),
                name="document_type_content",
                violation_error_message="A file document holds a file and no text, a text document no file.",
            ),
        ]

    def __str__(self):
        return self.name
