import hashlib
import shutil
import tempfile

from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from pydantic import ValidationError as PydanticValidationError

from base.models import FileReference
from core.services import Environment
from website.models import Media
from website.schemas import MediaCreateSchema, MediaFilterSchema
from website.services import MediaService

PAYLOAD = b"%PDF-1.4 not really a pdf"


class TestMediaService(TestCase):

    @classmethod
    def setUpClass(cls):
        # `StorageSettingsMixin` listens on `setting_changed` and drops its
        # cached `location`, so the module-level storage instances really do
        # follow `MEDIA_ROOT` here.
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(MediaService)

    def _create(self, filename="report.pdf", payload=PAYLOAD):
        data = MediaCreateSchema(
            content=SimpleUploadedFile(filename, payload, content_type="application/pdf")
        )
        return async_to_sync(self.service.create)([data])[0]

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_computes_the_checksum(self):
        media = self._create()

        self.assertEqual(
            Media.objects.get(pk=media.pk).checksum,
            hashlib.sha1(PAYLOAD).hexdigest(),
        )

    def test_create_computes_the_mimetype_from_the_filename(self):
        media = self._create(filename="report.pdf")

        self.assertEqual(Media.objects.get(pk=media.pk).mimetype, "application/pdf")

    def test_create_keeps_the_uploaded_filename_as_the_name(self):
        # Captured before the INSERT: `FileField.pre_save` replaces
        # `content.name` with the stored path, so reading it afterwards would
        # give `website/2026/09/report.pdf` instead.
        media = self._create(filename="report.pdf")

        self.assertEqual(Media.objects.get(pk=media.pk).name, "report.pdf")

    def test_create_commits_the_file_to_storage(self):
        media = self._create()

        stored = Media.objects.get(pk=media.pk)
        self.assertTrue(stored.content.name.startswith("website/"))
        # A `FileField` holds the *symlink* path: this storage keeps the bytes
        # once, under `path()` (`_filestore/<sha1>`), and points a symlink at
        # them from `symlink_path()`. Hence `symlink_exists`, not `exists` --
        # the same reason `size()` stats `symlink_path(name)`.
        self.assertTrue(stored.content.storage.symlink_exists(stored.content.name))

    def test_create_files_the_bytes_under_their_own_checksum(self):
        # Regression guard for the mandatory `seek(0)`: the storage reads the
        # stream again to derive the `FileReference.store_path` and never
        # rewinds, so a cursor left at EOF files every upload under the SHA1 of
        # the empty string.
        media = self._create()

        empty_sha1 = hashlib.sha1(b"").hexdigest()
        reference = FileReference.objects.get(symbolic_path=media.content.name)
        self.assertEqual(reference.checksum, hashlib.sha1(PAYLOAD).hexdigest())
        self.assertNotEqual(reference.checksum, empty_sha1)

    def test_two_uploads_of_different_bytes_are_stored_apart(self):
        first = self._create(filename="a.pdf", payload=b"first")
        second = self._create(filename="b.pdf", payload=b"second")

        self.assertNotEqual(
            Media.objects.get(pk=first.pk).checksum,
            Media.objects.get(pk=second.pk).checksum,
        )
        paths = set(
            FileReference.objects.filter(
                symbolic_path__in=[first.content.name, second.content.name]
            ).values_list("store_path", flat=True)
        )
        self.assertEqual(len(paths), 2)

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    def test_create_without_a_file_is_rejected_by_the_schema(self):
        with self.assertRaises(PydanticValidationError):
            MediaCreateSchema()

    def test_create_refuses_a_plain_string(self):
        # The factory would have typed a `FileField` as `str`, which cannot
        # carry bytes; the explicit `UploadedFile` annotation is what rejects it.
        with self.assertRaises(PydanticValidationError):
            MediaCreateSchema(content="website/2026/09/report.pdf")

    def test_only_the_content_is_writable(self):
        # Letting a caller set `checksum`, `name` or `mimetype` would let it lie
        # about what it uploaded.
        self.assertEqual(set(MediaCreateSchema.model_fields), {"content"})

    def test_the_service_exposes_no_update(self):
        # A media is immutable: replacing the bytes is a create plus a delete.
        self.assertFalse(hasattr(self.service, "update"))

    # ------------------------------------------
    # Tests Read / Delete
    # ------------------------------------------

    def test_read_filters_on_the_checksum(self):
        media = self._create()

        queryset = async_to_sync(self.service.read)(
            MediaFilterSchema(checksum=hashlib.sha1(PAYLOAD).hexdigest())
        )

        self.assertEqual([m.pk for m in queryset], [media.pk])

    def test_delete_removes_the_stored_file(self):
        media = self._create()
        stored = Media.objects.get(pk=media.pk)
        storage, path = stored.content.storage, stored.content.name
        self.assertTrue(storage.symlink_exists(path))

        async_to_sync(self.service.delete)({"id": media.pk})

        self.assertFalse(Media.objects.filter(pk=media.pk).exists())
        # `CleanupFileQuerysetMixin.delete` is what reaches the storage, which
        # drops the symlink and -- no other reference being left -- the bytes.
        self.assertFalse(storage.symlink_exists(path))
        self.assertFalse(FileReference.objects.filter(symbolic_path=path).exists())
