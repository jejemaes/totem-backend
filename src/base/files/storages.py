import os
import pathlib
from urllib.parse import urljoin

from django.db.models import Subquery
from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.core.files.utils import validate_file_name
from django.utils._os import safe_join
from django.utils.deconstruct import deconstructible
from django.utils.encoding import filepath_to_uri

from base.choices import FileReferencePrivacy
from base.models import FileReference
from core.db.tenancy import current_database
from core.utils import signing

# -----------------------------------------------
# Media FileSystem Storages
# -----------------------------------------------

def private_media_salt():
    """ Salt of the signed URLs of the private media, bound to the database.

    A URL signed for a tenant is then refused on any other: the same symbolic
    path may exist in both, pointing at a different file.
    """
    return f"private-media:{current_database()}"


@deconstructible(path="base.files.storages.PublicMediaFileSystemStorage")
class PublicMediaFileSystemStorage(FileSystemStorage):
    """
    Standard filesystem storage

    Each tenant database has its own root, `MEDIA_ROOT/<db_name>/`, holding the
    `_filestore` and the `public` and `private` media stores. The root is
    computed on each access, not cached as in `FileSystemStorage`: the storage
    instances are created once, at import, on the model fields.
    """

    FILESTORE_DIR = '_filestore'
    PRIVACY = FileReferencePrivacy.PUBLIC

    @property
    def base_location(self):
        return os.path.join(self._value_or_setting(self._location, settings.MEDIA_ROOT), current_database())

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def symlink_path(self, name):
        return safe_join(self.location, self.PRIVACY, name)

    def symlink_exists(self, name):
        return os.path.lexists(self.symlink_path(name))

    def _save(self, name, content):
        bin_data = content.read()
        data = FileReference.precompute_values(bin_data, name)
        symbolic_path = name
        store_path = data['store_path']

        # Create file
        absolute_file_path = self.path(store_path)
        if not self.exists(store_path):
            store_path = super()._save(store_path, content)

        # Create symlink
        symbolic_path = self._symlink_get_available_name(symbolic_path, max_length=256)
        absolute_link_path = self.symlink_path(symbolic_path)
        self._ensure_intermediate_directory(absolute_link_path)
        try:
            # Relative, so that the root of a tenant can be moved as a whole.
            os.symlink(
                os.path.relpath(absolute_file_path, os.path.dirname(absolute_link_path)),
                absolute_link_path,
            )
        except FileExistsError:
            pass

        # Create file reference
        values = dict(data)
        values['privacy'] = self.PRIVACY
        values['symbolic_path'] = symbolic_path
        file_reference = FileReference(**values)
        FileReference.objects.bulk_create(
            [file_reference],
            update_conflicts=True,
            update_fields=[
                "symbolic_path",
                "store_path",
                "checksum",
                "mimetype",
                "privacy",
            ],
            unique_fields=[
                'symbolic_path',
                'privacy',
            ]
        )
        return symbolic_path  # the symbolic link need to be store in the FileField

    def delete(self, name):
        sub = FileReference.objects.filter(privacy=self.PRIVACY, symbolic_path=name)
        file_references = FileReference.objects.filter(checksum__in=Subquery(sub.values_list('checksum')))

        if len(file_references) == 1:
            link_to_remove = {ref.symbolic_path for ref in file_references}
            file_to_remove = {ref.store_path for ref in file_references}
            file_references.delete()
        else:
            link_to_remove = {ref.symbolic_path for ref in sub}
            file_to_remove = set()  # other reference exist, don't remove the target file
            sub.delete()

        for filename in file_to_remove:
            super().delete(filename)

        for link in link_to_remove:
            try:
                os.unlink(self.symlink_path(link))
            except FileNotFoundError:
                # FileNotFoundError is raised if the file or directory was removed
                # concurrently.
                pass

    def path(self, name):
        name = os.path.join(self.FILESTORE_DIR, name)
        return super().path(name)

    def size(self, name):
        return os.path.getsize(self.symlink_path(name))

    def url(self, name):
        if self.base_url is None:
            raise ValueError("This file is not accessible via a URL.")
        url = filepath_to_uri(name)
        if url is not None:
            url = url.lstrip("/")
        return urljoin(self.base_url, self.PRIVACY + '/' + url)

    def _ensure_intermediate_directory(self, absolute_link_path):
        directory = os.path.dirname(absolute_link_path)
        try:
            if self.directory_permissions_mode is not None:
                # Set the umask because os.makedirs() doesn't apply the "mode"
                # argument to intermediate-level directories.
                old_umask = os.umask(0o777 & ~self.directory_permissions_mode)
                try:
                    os.makedirs(
                        directory, self.directory_permissions_mode, exist_ok=True
                    )
                finally:
                    os.umask(old_umask)
            else:
                os.makedirs(directory, exist_ok=True)
        except FileExistsError:
            pass  # ignore if dir path already exists

    def _symlink_get_available_name(self, name, max_length=None):
        """
        Return a filename that's free on the target storage system and
        available for new content to be written to.
        Note: almost 100% copy/paste from 'super' (`get_available_name` method), as
        we handle symlink here. So, only the loop condition changed.
        """
        name = str(name).replace("\\", "/")
        dir_name, file_name = os.path.split(name)
        if ".." in pathlib.PurePath(dir_name).parts:
            raise SuspiciousFileOperation(
                "Detected path traversal attempt in '%s'" % dir_name
            )
        validate_file_name(file_name)
        file_root, file_ext = os.path.splitext(file_name)
        # If the filename already exists, generate an alternative filename
        # until it doesn't exist.
        # Truncate original name if required, so the new filename does not
        # exceed the max_length.
        while self.symlink_exists(name) or (max_length and len(name) > max_length):
            # file_ext includes the dot.
            name = os.path.join(
                dir_name, self.get_alternative_name(file_root, file_ext)
            )
            if max_length is None:
                continue
            # Truncate file_root if max_length exceeded.
            truncation = len(name) - max_length
            if truncation > 0:
                file_root = file_root[:-truncation]
                # Entire file_root was truncated in attempt to find an
                # available filename.
                if not file_root:
                    raise SuspiciousFileOperation(
                        'Storage can not find an available filename for "%s". '
                        "Please make sure that the corresponding file field "
                        'allows sufficient "max_length".' % name
                    )
                name = os.path.join(
                    dir_name, self.get_alternative_name(file_root, file_ext)
                )
        return name


class PrivateMediaFileSystemStorage(PublicMediaFileSystemStorage):
    PRIVACY = FileReferencePrivacy.PRIVATE

    def __init__(
        self,
        location=None,
        base_url=None,
        file_permissions_mode=None,
        directory_permissions_mode=None,
        expiration_hours=None
    ):
        self.expiration_hours = expiration_hours or 1  # 1h default
        super().__init__(location=location, base_url=base_url, file_permissions_mode=file_permissions_mode, directory_permissions_mode=directory_permissions_mode)

    def url(self, name):
        url = super().url(name)
        return signing.sign_url(url, hours=self.expiration_hours, salt=private_media_salt())
