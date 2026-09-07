"""Schemas for `website.Media`.

Two things set this resource apart from the others, both worth knowing before
wiring a controller on it:

  * `MediaCreateSchema` is not a JSON body. It carries an actual uploaded file,
    so a controller must accept `multipart/form-data` and declare the field with
    ninja's `File(...)`. No controller in the project does file upload yet.
  * `content` does not serialize consistently. Ninja's `DjangoGetter` maps a
    `FieldFile` to its `.url`, so a retrieve or a create returns the public URL;
    a list route goes through `model_instance_to_dict`, which reads
    `instance.__dict__` and therefore returns the bare stored path. The same
    asymmetry already applies to `UserSchema.avatar`.
"""

from typing import Optional

from ninja import FilterSchema
from ninja.files import UploadedFile
from pydantic import Field

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
