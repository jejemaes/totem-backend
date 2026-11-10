import shutil
import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from user.models import User


class TestCleanupFileModelMixin(TestCase):
    """Through `User.avatar`, a model of the project carrying the mixin."""

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def test_save_with_a_new_file(self):
        """`FieldFile.save` leaves the stored name, a `str`, on the instance:
        the mixin used to read `.name` on it and fail after the INSERT."""
        user = User.objects.create(
            username="Sam",
            email="sam@shire.me",
            avatar=ContentFile(b"\x89PNG", name="sam.png"),
        )
        self.assertTrue(User.objects.get(pk=user.pk).avatar.name)
        # And a second save does not take the file for a replaced one.
        user.save()
        self.assertTrue(user.avatar.storage.symlink_exists(user.avatar.name))
