"""Schemas for `document.Document`.

`DocumentCreateSchema` carries an actual uploaded file, like
`MediaCreateSchema`: a controller must accept `multipart/form-data` and declare
the file as a parameter of its own.
"""

from typing import List, Optional

from django.db.models import Q
from ninja.files import UploadedFile
from pydantic import Field, field_validator, model_validator
from ulid import ULID

from contact.schemas import ContactDisplayNameSchema
from core.api.filters import FilterSchema, MultiValue
from core.schemas import ModelSchema
from document.models import Document
from user.schemas import UserDisplayNameSchema

from .tags import DocumentTagDisplayNameSchema

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class DocumentDisplayNameSchema(ModelSchema):
    class Meta:
        model = Document
        fields = ["id", "name"]


class DocumentSchema(ModelSchema):
    # Without these annotations a relation serializes to its bare pk, and is
    # not prefetched.
    user: Optional[UserDisplayNameSchema] = None
    contact: Optional[ContactDisplayNameSchema] = None
    tags: Optional[List[DocumentTagDisplayNameSchema]] = None

    class Meta:
        model = Document
        fields = [
            "id",
            "name",
            "document_type",
            "file",
            "thumbnail",
            "text_content",
            "mimetype",
            "checksum",
            "size",
            "date",
            "user",
            "contact",
            "tags",
            "create_date",
            "update_date",
        ]
        optional_fields = "__all__"

    # `check_fields=False`: `file` and `thumbnail` are derived from the model by
    # the metaclass, after the class body; see `MediaListSchema`.
    @field_validator("file", "thumbnail", mode="before", check_fields=False)
    @classmethod
    def _stored_path_to_url(cls, value, info):
        """The stored path -> the signed URL, whatever route serializes it.

        A list route serializes `instance.__dict__`, the bare stored path, while
        a retrieve gets the `.url` of the `FieldFile` from ninja's `DjangoGetter`:
        see `MediaListSchema._stored_path_to_url`, whose leading-slash test this
        reuses. Without it a listed file would not be downloadable.
        """
        if value == "":
            # No file (a text, or no thumbnail): `null`, as a retrieve gives it
            # -- ninja's getter maps an empty `FieldFile` to None.
            return None
        if isinstance(value, str) and not value.startswith("/"):
            return Document._meta.get_field(info.field_name).storage.url(value)
        return value


class DocumentCreateSchema(ModelSchema):
    # The generated field would be a `str`, which cannot carry bytes; see
    # `MediaCreateSchema.content`.
    file: Optional[UploadedFile] = None

    class Meta:
        model = Document
        fields = ["name", "document_type", "file", "text_content", "date", "user", "contact", "tags"]
        optional_fields = ["name", "file", "text_content", "date", "user", "contact", "tags"]

    @model_validator(mode="after")
    def _name_from_file(self):
        """A file document left unnamed takes the name of its file.

        Here, and not with the other derived values of
        `DocumentService._create_preprocess_values`: `name` is a NOT NULL column
        the create schema declares, so a `None` would be refused by
        `to_internal_values` -- on `name` -- before any service hook runs. The
        default is a function of the input alone, which is what a schema may
        compute.
        """
        if not self.name and self.file is not None:
            self.name = self.file.name
        return self


class DocumentCreateFormSchema(ModelSchema):
    """The form fields of a creation, sent as `multipart/form-data` beside the
    `file` part: `DocumentCreateSchema` without the file, which a multipart
    route must take as a parameter of its own (see `DocumentController`)."""

    class Meta:
        model = Document
        fields = ["name", "document_type", "text_content", "date", "user", "contact", "tags"]
        optional_fields = ["name", "text_content", "date", "user", "contact", "tags"]


class DocumentUploadFormSchema(ModelSchema):
    """The form fields of an upload: what every document of the batch shares."""

    class Meta:
        model = Document
        fields = ["user", "contact", "tags"]
        optional_fields = "__all__"


class DocumentUpdateSchema(ModelSchema):
    class Meta:
        model = Document
        fields = ["name", "text_content", "date", "user", "contact", "tags"]
        optional_fields = "__all__"


# No `thumbnail` in any write schema: it is made from the file at creation.
# No `document_type` nor `file` in the update schema: replacing a file means
# creating a new document, which keeps `checksum`, `mimetype` and `size` true
# to the file, as for `Media`. `mimetype`, `checksum` and `size` are in no
# write schema: they are derived, and a caller setting them could lie about
# what it uploaded.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


def _documents_through_tags(**lookups):
    """The pks of the documents linked to a tag matching `lookups`.

    A subquery rather than a join on `tags__...`: through a to-many relation, a
    document carrying two of the tags asked would come out twice (see
    `MultiValue`).
    """
    return Document.tags.through.objects.filter(
        **{f"documenttag__{lookup}": value for lookup, value in lookups.items()}
    ).values("document_id")


class DocumentFilterSchema(FilterSchema):
    # `ULID` rather than `str`: a malformed id is refused (422) instead of
    # silently matching nothing.
    tag: MultiValue(ULID, allow_null=False) = Field(
        None,
        title="Tag",
        description="Comma-separated identifiers of tags: the documents carrying any of them.",
    )
    tag_category: MultiValue(ULID, allow_null=False) = Field(
        None,
        title="Tag Category",
        description="Comma-separated identifiers of tag categories: the documents "
        "carrying a tag of any of them.",
    )
    contact: MultiValue(ULID) = Field(
        None,
        q="contact__id",
        title="Contact",
        description="Comma-separated identifiers of the contacts of the documents, "
        "`null` for the documents filed under none.",
    )
    document_type: MultiValue(str, allow_null=False) = Field(
        None,
        q="document_type",
        title="Type",
        description="Comma-separated types of the documents (`file`, `text`).",
    )
    mimetype: Optional[str] = Field(
        None,
        q="mimetype__istartswith",
        title="Mimetype",
        description="Start of the mimetype: `image/` for every image, `application/pdf`...",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )

    def filter_tag(self, value):
        if not value:
            return Q()
        return Q(pk__in=_documents_through_tags(id__in=value))

    def filter_tag_category(self, value):
        if not value:
            return Q()
        return Q(pk__in=_documents_through_tags(category_id__in=value))
