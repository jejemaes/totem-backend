import hashlib
import mimetypes
import typing as t
import zoneinfo

from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from base.files.validation import validate_upload
from core.services import (
    CreateMixin,
    DeleteMixin,
    ReadMixin,
    ResequenceMixin,
    ServiceBase,
    UpdateMixin,
)
from core.services.exceptions import ServiceValidationError, ServiceValidationMultiError
from document.choices import DocumentType
from document.models import Document, DocumentTag, DocumentTagCategory
from document.models.document import text_size
from document.schemas import (
    DocumentCreateSchema,
    DocumentTagCategoryCreateSchema,
    DocumentTagCategoryUpdateSchema,
    DocumentTagCreateSchema,
    DocumentTagUpdateSchema,
    DocumentUpdateSchema,
)


class DocumentTagCategoryService(
    CreateMixin[DocumentTagCategoryCreateSchema],
    ReadMixin,
    UpdateMixin[DocumentTagCategoryUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[DocumentTagCategory],
):
    """No hook: the unique name is a constraint of the model. Deleting a
    category that still has tags is refused by their `PROTECT` foreign key,
    reported as a validation error by `DeleteMixin`."""


class DocumentTagService(
    CreateMixin[DocumentTagCreateSchema],
    ReadMixin,
    UpdateMixin[DocumentTagUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[DocumentTag],
):
    """No hook: the required category is resolved through its service
    (`RelationNotFound`), and the unique name within a category is a constraint
    of the model."""


class DocumentService(
    CreateMixin[DocumentCreateSchema],
    ReadMixin,
    UpdateMixin[DocumentUpdateSchema],
    DeleteMixin,
    ServiceBase[Document],
):
    """Two ways to create: `create`, one document from a form, the only one for
    a text; and `upload`, many files dropped at once.

    `mimetype`, `checksum` and `size` are derived from the content by
    `_create_preprocess_values`, after validation and before the INSERT, which
    is also where `FileField.pre_save` commits the file to storage. They are on
    no write schema, so a client cannot set them; and since neither the type nor
    the file can change after creation, only the size of a text ever moves --
    which `DocumentQuerySet.update` follows.
    """

    # A security floor for a private store, not a policy on what a document may
    # be: no allow-list, any type but the executable ones of `validate_upload`.
    # Larger than `MediaService`'s, for scanned PDFs.
    MAX_UPLOAD_SIZE = 20 * 1024 * 1024
    # Bounds the size of one `upload` request, on top of the size of each file.
    MAX_UPLOAD_COUNT = 20

    async def upload(
        self,
        files: t.List[UploadedFile],
        tags: t.Optional[t.List] = None,
        user=None,
        contact=None,
    ) -> t.List[Document]:
        """Create one `file` document per uploaded file, named after the file.

        Through `create`, not beside it: the same access rules, the same
        `validate_data`, one transaction. So it is all or nothing -- one file
        refused and none is created -- and the error is keyed by the position of
        the file, so the client knows which one. `tags`, `user` and `contact` go
        to every document of the batch; the rest is edited afterwards, one by one.

        Raises `ServiceValidationMultiError` on `files` beyond `MAX_UPLOAD_COUNT`.
        """
        if len(files) > self.MAX_UPLOAD_COUNT:
            raise ServiceValidationMultiError(
                {"files": ServiceValidationError(
                    f"Too many files ({len(files)}). The maximum is {self.MAX_UPLOAD_COUNT} per upload.",
                    key="files",
                )},
                code="invalid_data",
            )
        # Only what is given: a field set, even to None, is not filled with its
        # default by `create`.
        common = {}
        if tags is not None:
            common["tags"] = tags
        if user is not None:
            common["user"] = user
        if contact is not None:
            common["contact"] = contact
        return await self.create([
            DocumentCreateSchema(document_type=DocumentType.FILE, file=file, **common)
            for file in files
        ])

    async def _default_values(self, fields=None):
        """A document not given a user is the acting user's, as a budget is, and
        one not given a date is dated today.

        Here rather than on the model, which knows neither the acting user nor
        their timezone: today is the day of the environment's `tz`, not of the
        server, so a document filed late in the evening is not dated tomorrow.
        `create` fills from it only the fields an input leaves out, so a value
        explicitly set to null stays null. Applies to `upload` too, which leaves
        both out. No default user for an API key, which acts as no user.
        """
        values = await super()._default_values(fields)
        if self.user is not None and (fields is None or "user" in fields):
            values["user"] = self.user.pk
        if fields is None or "date" in fields:
            values["date"] = timezone.localdate(timezone=zoneinfo.ZoneInfo(self.tz))
        return values

    def validate_data(self, data, instance):
        """The content must match the type, checked before the INSERT: a refused
        upload writes nothing to the storage.

        The `document_type_content` constraint says the same for every writer,
        but only after the file is committed, and with an error naming no field.
        """
        if instance is None:
            upload = data.get("file")
            if data["document_type"] == DocumentType.FILE:
                if upload is None:
                    raise self.ValidationError("A file document needs a file.", key="file")
                if data.get("text_content") is not None:
                    raise self.ValidationError("A file document holds no text.", key="text_content")
                validate_upload(upload, self.MAX_UPLOAD_SIZE, key="file")
            elif upload is not None:
                raise self.ValidationError("A text document holds no file.", key="file")
        elif instance.document_type == DocumentType.FILE and data.get("text_content") is not None:
            raise self.ValidationError("A file document holds no text.", key="text_content")

    def _create_preprocess_values(self, internal_data):
        for values in internal_data:
            if values["document_type"] == DocumentType.FILE:
                upload = values["file"]
                upload.seek(0)
                bin_data = upload.read()
                # Mandatory, not defensive: the storage reads the stream again
                # when `FileField.pre_save` commits it, and never rewinds; see
                # `MediaQuerySet.bulk_create`.
                upload.seek(0)
                values["checksum"] = hashlib.sha1(bin_data).hexdigest()
                # From the filename, as `validate_upload` checked it.
                values["mimetype"] = mimetypes.guess_type(upload.name or "")[0]
                values["size"] = len(bin_data)
            else:
                values["mimetype"] = "text/html"
                values["size"] = text_size(values.get("text_content"))
        return internal_data
