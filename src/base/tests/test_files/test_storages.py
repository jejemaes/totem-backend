import io
import os
import shutil
import tempfile

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from base.choices import FileReferencePrivacy
from base.files.storages import (
    PrivateMediaFileSystemStorage,
    PublicMediaFileSystemStorage,
    private_media_salt,
)
from base.models import FileReference
from core.db.tenancy import current_database, use_database
from core.utils import signing


class MediaRootMixin:
    """ A fresh `MEDIA_ROOT` per test. """

    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)


class StorageLocationTestCase(MediaRootMixin, SimpleTestCase):

    def test_location_is_the_root_of_the_current_database(self):
        storage = PublicMediaFileSystemStorage()
        self.assertEqual(storage.location, os.path.join(self.media_root, current_database()))
        with use_database("tenant_a"):
            # Same instance: the storages of the model fields are created once.
            self.assertEqual(storage.location, os.path.join(self.media_root, "tenant_a"))
            self.assertEqual(
                storage.path("ab/abcd"),
                os.path.join(self.media_root, "tenant_a", "_filestore", "ab", "abcd"),
            )
            self.assertEqual(
                storage.symlink_path("website/a.png"),
                os.path.join(self.media_root, "tenant_a", "public", "website", "a.png"),
            )

    def test_public_url_unchanged(self):
        """ The domain names the tenant: the URL does not. """
        with use_database("tenant_a"):
            self.assertEqual(PublicMediaFileSystemStorage().url("website/a.png"), "/media/public/website/a.png")

    def test_private_url_only_valid_for_its_database(self):
        url = PrivateMediaFileSystemStorage().url("user/avatar.png")
        self.assertTrue(signing.check_signature(url, salt=private_media_salt()))
        with use_database("tenant_a"):
            self.assertFalse(signing.check_signature(url, salt=private_media_salt()))


class StorageSaveTestCase(MediaRootMixin, TestCase):

    def test_save_under_the_database_root_with_relative_symlink(self):
        storage = PublicMediaFileSystemStorage()
        name = storage.save("website/2024/a.txt", ContentFile(b"hello"))

        link = storage.symlink_path(name)
        self.assertTrue(link.startswith(os.path.join(self.media_root, current_database(), "public")))
        self.assertFalse(os.path.isabs(os.readlink(link)))
        reference = FileReference.objects.get(symbolic_path=name)
        self.assertEqual(os.path.realpath(link), os.path.realpath(storage.path(reference.store_path)))
        with open(link, "rb") as f:
            self.assertEqual(f.read(), b"hello")


class PrivateMediaViewTestCase(MediaRootMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.storage = PrivateMediaFileSystemStorage()
        self.name = self.storage.save("user/avatar.txt", ContentFile(b"secret"))
        self.reference = FileReference.objects.get(
            privacy=FileReferencePrivacy.PRIVATE, symbolic_path=self.name
        )

    def test_redirect_into_the_filestore_of_the_database(self):
        response = self.client.get(self.storage.url(self.name))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["X-Accel-Redirect"],
            f"/_media_internal/{current_database()}/_filestore/{self.reference.store_path}",
        )

    def test_url_signed_for_another_database_refused(self):
        # As `url()` signs it in `tenant_a` (a `TestCase` refuses the switch).
        url = signing.sign_url(f"/media/private/{self.name}", hours=1, salt="private-media:tenant_a")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class ClearFilestoreTestCase(MediaRootMixin, SimpleTestCase):

    def test_only_the_root_of_the_database(self):
        current = os.path.join(self.media_root, current_database(), "public", "a", "b")
        other = os.path.join(self.media_root, "tenant_a", "public", "c")
        os.makedirs(current)
        os.makedirs(other)

        call_command("clear_filestore", "--empty-dir")

        self.assertFalse(os.path.exists(os.path.join(self.media_root, current_database(), "public", "a")))
        self.assertTrue(os.path.isdir(other))

        call_command("clear_filestore", "--empty-dir", "--db-name", "tenant_a")
        self.assertFalse(os.path.exists(other))


class FilestoreToTenantLayoutTestCase(MediaRootMixin, SimpleTestCase):

    def setUp(self):
        super().setUp()
        # The single-tenant layout, with absolute symlinks.
        self.blob = os.path.join(self.media_root, "_filestore", "ab", "abcd")
        os.makedirs(os.path.dirname(self.blob))
        with open(self.blob, "wb") as f:
            f.write(b"content")
        for store, name in [("public", "website/2024/a.png"), ("private", "user/b.png")]:
            link = os.path.join(self.media_root, store, name)
            os.makedirs(os.path.dirname(link))
            os.symlink(self.blob, link)

    def test_move_and_relink(self):
        call_command("filestore_to_tenant_layout", "tenant_a", verbosity=0, stdout=io.StringIO())

        root = os.path.join(self.media_root, "tenant_a")
        for store in ["_filestore", "public", "private"]:
            self.assertFalse(os.path.exists(os.path.join(self.media_root, store)))
            self.assertTrue(os.path.isdir(os.path.join(root, store)))
        for link in [os.path.join(root, "public", "website/2024/a.png"), os.path.join(root, "private", "user/b.png")]:
            self.assertFalse(os.path.isabs(os.readlink(link)))
            with open(link, "rb") as f:
                self.assertEqual(f.read(), b"content")

        # The storage of that database finds the files where they now are.
        with use_database("tenant_a"):
            self.assertTrue(PublicMediaFileSystemStorage().symlink_exists("website/2024/a.png"))

    def test_dry_run_changes_nothing(self):
        call_command("filestore_to_tenant_layout", "tenant_a", "--dry-run", stdout=io.StringIO())
        self.assertFalse(os.path.exists(os.path.join(self.media_root, "tenant_a")))
        self.assertEqual(os.readlink(os.path.join(self.media_root, "public", "website/2024/a.png")), self.blob)

    def test_refuses_to_merge_into_an_existing_root(self):
        os.makedirs(os.path.join(self.media_root, "tenant_a", "public"))
        with self.assertRaises(CommandError):
            call_command("filestore_to_tenant_layout", "tenant_a", stdout=io.StringIO())
        # Nothing moved.
        self.assertTrue(os.path.isdir(os.path.join(self.media_root, "_filestore")))
