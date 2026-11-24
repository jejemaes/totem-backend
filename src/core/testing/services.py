import shutil
import tempfile

from django.test import override_settings

from core.services import Environment


class ServiceTestCaseMixin:
    """ What every service test case shares: how a service is built.

    Data does not belong here: each resource has its own `common_<resource>.py`.
    """

    def get_service(self, service_class, user=None, language="en-us", tz=None):
        """ The service, in a fresh `Environment` acting as `user`.

        Fresh on each call: an environment memoizes the roles of its user, so a
        service built before a test edits a role would keep applying the old
        rules. `user=None` is an anonymous caller, or an API key: no role, so no
        access rule applies to it.
        """
        return Environment(user=user, language=language, tz=tz).get(service_class)


class MediaRootTestMixin:
    """ A fresh `MEDIA_ROOT` for the class: what the tests upload stays there.

    `StorageSettingsMixin` listens on `setting_changed` and drops its cached
    `location`, so the module-level storage instances really do follow it.
    """

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
