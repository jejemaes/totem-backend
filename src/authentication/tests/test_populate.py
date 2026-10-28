import io

from django.contrib.auth import authenticate
from django.core.management import call_command
from django.test import TestCase

from authentication.apps import DEV_API_KEY_NAME, DEV_API_KEY_SECRET, DEV_PASSWORD
from authentication.models import ApiKey
from authentication.tokens import hash_secret
from user.models import User, UserRole


class PopulateLocalTestCase(TestCase):
    """ What `populate --env local` has to leave behind for a developer to
    authenticate at all.

    Run through the command rather than by calling the hook, so that the
    dependency on `user` -- which is what loads the users whose password is then
    set -- is exercised too.
    """

    def populate(self):
        call_command("populate", "authentication", "--env", "local", stdout=io.StringIO())

    def test_the_dev_password_lets_a_fixture_user_log_in(self):
        # The reason the hook exists: the hash in `user/fixtures/local/user.json`
        # has no known clear text, so without this nobody can obtain a token.
        self.populate()

        self.assertIsNotNone(authenticate(username="admin", password=DEV_PASSWORD))

    def test_the_dev_api_key_is_usable_and_powerless(self):
        self.populate()

        key = ApiKey.objects.get(name=DEV_API_KEY_NAME)
        # The documented secret, not a random one: a script written yesterday
        # must keep working after a repopulate.
        self.assertEqual(key.secret_hash, hash_secret(DEV_API_KEY_SECRET))
        self.assertEqual(key.scope, [])

    def test_populate_is_idempotent(self):
        self.populate()
        self.populate()

        self.assertEqual(ApiKey.objects.filter(name=DEV_API_KEY_NAME).count(), 1)
        self.assertIsNotNone(authenticate(username="admin", password=DEV_PASSWORD))


class PopulateSystemTestCase(TestCase):

    def test_the_admin_role_may_manage_api_keys(self):
        # A scope granted to no role is an endpoint nobody can reach, and
        # `totem.apikey.*` is `is_public=False`, so a role is the only way in.
        call_command("populate", "user", "--env", "system", stdout=io.StringIO())

        permissions = UserRole.objects.get(pk="USERTYPE_ADMIN").permissions
        self.assertIn("totem.apikey.create", permissions)
        self.assertIn("totem.apikey.read", permissions)
        self.assertIn("totem.apikey.delete", permissions)

    def test_the_token_cleanup_is_scheduled(self):
        from django_celery_beat.models import PeriodicTask

        call_command("populate", "authentication", "--env", "system", stdout=io.StringIO())

        self.assertTrue(
            PeriodicTask.objects.filter(task="authentication.tasks.clear_tokens").exists()
        )
