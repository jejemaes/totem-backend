"""Schemas for `website.Media`.

Two things set this resource apart from the others, both worth knowing before
wiring a controller on it:

  * `MediaCreateSchema` is not a JSON body. It carries an actual uploaded file,
    so a controller must accept `multipart/form-data` and declare the file as a
    parameter of its own -- annotating this whole schema with `File()` does not
    work, since ninja builds no flatten map for the file source. `MediaController`
    is the only controller in the project that does file upload; see its
    `_annotate_create_view_function`.
  * `content` does not serialize consistently. Ninja's `DjangoGetter` maps a
    `FieldFile` to its `.url`, so a retrieve or a create returns the public URL;
    a list route goes through `model_instance_to_dict`, which reads
    `instance.__dict__` and therefore returns the bare stored path. The same
    asymmetry already applies to `UserSchema.avatar`.

    `MediaListSchema` below is the one that closes it, for its own route only:
    every client of `content` puts it in an `<img src>`, and a schema whose
    meaning depended on which route served it would be a trap rather than a
    contract.
"""

from typing import Optional

from ninja import FilterSchema
from ninja.files import UploadedFile
from pydantic import Field, field_validator

from core.schemas import ModelSchema
from website.models import Media

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class MediaDisplayNameSchema(ModelSchema):
    class Meta:
        model = Media
        fields = ["id", "name"]


class MediaSchema(ModelSchema):
    class Meta:
        model = Media
        fields = ["id", "name", "content", "checksum", "mimetype", "create_date"]
        optional_fields = "__all__"


class MediaListSchema(ModelSchema):
    """One row of the media library, and deliberately not `MediaSchema`.

    Its only client is the editor's image picker, which needs a thumbnail, a
    caption and a way to tell an image from a PDF -- so `checksum` and
    `create_date` are left out rather than shipped "in case". A narrower list
    row is also what keeps a listing of a general file store cheap.

    `content` is normalised to the public URL below, because that is the ONE
    thing the picker does with it. Without it a list row would carry the bare
    stored path (see the module docstring) and every thumbnail would 404.
    """

    class Meta:
        model = Media
        fields = ["id", "name", "content", "mimetype"]
        optional_fields = "__all__"

    # `check_fields=False` is required, not defensive: pydantic collects
    # decorators while the class body is being built, and `content` is not in it
    # -- `ModelSchema`'s metaclass derives the field from the model afterwards.
    # Without it every import of this module raises `decorator-missing-field`.
    @field_validator("content", mode="before", check_fields=False)
    @classmethod
    def _stored_path_to_url(cls, value):
        """The stored path -> the public URL, the way a `FieldFile` would.

        `mode="before"` because the value arrives as the raw column: a list route
        serialises `instance.__dict__`, which holds what the storage returned
        from `_save` -- the symbolic path, `website/YYYY/MM/name.png`.

        The leading-slash test is what makes the schema safe on any route: a
        value read off an instance has already been mapped to its `.url` by
        ninja's `DjangoGetter`, and prefixing that a second time would produce
        `/media/public/media/public/...`. A stored path never starts with a
        slash; a URL always does.
        """
        if isinstance(value, str) and value and not value.startswith("/"):
            return Media._meta.get_field("content").storage.url(value)
        return value


class MediaCreateSchema(ModelSchema):

    # The generated field would be a `str` -- `convert_db_field` maps every
    # `FileField` to `str` -- which cannot carry bytes. An annotation wins over
    # the model-derived definition (the metaclass passes annotations as
    # `custom_fields`, which overwrite `definitions`), and ninja's
    # `UploadedFile` validates that the value really is a django upload.
    content: UploadedFile

    class Meta:
        model = Media
        fields = ["content"]


# The upload is the *only* writable field: `name`, `checksum` and `mimetype` are
# derived from the file itself by `MediaQuerySet.bulk_create`, and letting a
# caller set them would let it lie about what it uploaded. There is no
# `MediaUpdateSchema` -- a media is immutable, see `MediaService`.

# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class MediaFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the name.",
    )
    mimetype: Optional[str] = Field(
        None,
        q="mimetype__icontains",
        title="Mimetype",
        description="Search term in the mimetype.",
    )
    checksum: Optional[str] = Field(
        None,
        q="checksum",
        title="Checksum",
        description="Exact SHA1 of the binary content, to look a known file up.",
    )
    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )


class MediaListFilterSchema(FilterSchema):
    """The list route's filters: one search box, and nothing else.

    Separate from `MediaFilterSchema` rather than a reuse of it. That one is the
    SERVICE's filter surface -- `checksum` is how a caller looks a known file up
    without downloading it, and the service tests rely on it -- while this one is
    the public query string of a route whose only client is a picker with a
    search box. Exposing `checksum` there would publish a lookup nobody typed.
    """

    search: Optional[str] = Field(
        None,
        q=["name__icontains"],
        title="Search Term",
        description="Search term in the name.",
    )
