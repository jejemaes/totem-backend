import uuid
import hashlib
import mimetypes
from django.db import models

from base.files.storages import PublicMediaFileSystemStorage
from base.models.mixins import CleanupFileQuerysetMixin, CleanupFileModelMixin


class MediaQuerySet(CleanupFileQuerysetMixin, models.QuerySet):

    def bulk_create(self, objs, *args, **kwargs):
        """Derive `checksum`, `mimetype` and `name` from the uploaded file.

        It has to happen before the INSERT: that is where `FileField.pre_save`
        commits the file to storage, and after that `content.name` holds the
        stored path, not the uploaded filename. `Model.save()` -- and with it
        the admin form's `clean()`, the only caller of `precompute_values`
        today -- is never called on the service write path.
        """
        objs = list(objs)
        for obj in objs:
            if obj.checksum:
                continue  # explicitly provided by the caller
            file = obj.content
            if not file:
                continue  # let the NOT NULL constraint report it
            filename = file.name
            file.seek(0)
            bin_data = file.read()
            # Mandatory, not defensive: `PublicMediaFileSystemStorage._save`
            # reads the stream again to derive the `FileReference.store_path`
            # and never rewinds. A cursor left at EOF makes it hash `b""` and
            # file every upload under the SHA1 of the empty string.
            file.seek(0)
            for fname, value in Media.precompute_values(bin_data, filename).items():
                setattr(obj, fname, value)
        return super().bulk_create(objs, *args, **kwargs)


class Media(CleanupFileModelMixin, models.Model):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, null=False, primary_key=True
    )
    name = models.CharField(
        "Name", max_length=256, null=False, blank=False, help_text="Path in the filestore"
    )
    content = models.FileField(
        storage=PublicMediaFileSystemStorage(),
        upload_to="website/%Y/%m",
        null=False,
        max_length=256,
        blank=False,
    )
    checksum = models.CharField(
        "Checksum", max_length=128, null=False, blank=False, help_text="SHA1 of the binary data of the file"
    )
    mimetype = models.CharField("Mimetype", max_length=64, null=True, blank=True)
    create_date = models.DateTimeField("Create Date", auto_now_add=True)

    objects = MediaQuerySet.as_manager()

    class Meta:
        verbose_name = "Media"
        verbose_name_plural = "Medias"

    @classmethod
    def precompute_values(cls, bin_data, filename=None):
        checksum = hashlib.sha1(bin_data or b'').hexdigest()
        mimetype = mimetypes.guess_type(filename)[0] if filename else None
        return {
            'checksum': checksum,
            'mimetype': mimetype,
            'name': filename,
        }
