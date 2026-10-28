import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from authentication.models import ApiKey
from authentication.tokens import hash_secret


class CreateApiKeyCommandTestCase(TestCase):

    def create(self, *args, **options):
        """ Run the command and return what it printed on stdout: the secret alone. """
        stdout = io.StringIO()
        call_command("create_api_key", *args, stdout=stdout, stderr=io.StringIO(), **options)
        return stdout.getvalue().strip()

    def test_the_printed_secret_is_the_one_stored_hashed(self):
        secret = self.create("Nightly Export", scopes="totem.country.read")

        key = ApiKey.objects.get(name="Nightly Export")
        self.assertEqual(key.secret_hash, hash_secret(secret))
        # The whole contract of the command: the clear text crossed the terminal
        # and nothing else.
        self.assertNotIn(secret, [key.secret_hash, key.name])

    def test_the_scopes_are_stored(self):
        self.create("Reader", scopes="totem.country.read,totem.contact.read")

        self.assertEqual(
            ApiKey.objects.get(name="Reader").scope,
            ["totem.country.read", "totem.contact.read"],
        )

    def test_an_empty_scope_list_creates_a_powerless_key(self):
        # `--scopes` is mandatory, but granting nothing stays expressible.
        self.create("Powerless", scopes="")

        self.assertEqual(ApiKey.objects.get(name="Powerless").scope, [])

    def test_an_unknown_scope_is_refused(self):
        # `bulk_create` validates nothing, so without this check the command
        # would quietly produce a key that is forbidden everywhere.
        with self.assertRaises(CommandError):
            self.create("Typo", scopes="totem.contry.read")

        self.assertFalse(ApiKey.objects.exists())

    def test_a_non_public_scope_is_refused(self):
        # `totem.apikey.*` is registered `is_public=False` so that no key can
        # mint keys; a shell is not an exception to that.
        with self.assertRaises(CommandError):
            self.create("Bootstrapper", scopes="totem.apikey.create")

        self.assertFalse(ApiKey.objects.exists())

    def test_a_duplicate_name_is_an_error_not_an_integrity_error(self):
        self.create("Nightly Export", scopes="")

        with self.assertRaises(CommandError):
            self.create("Nightly Export", scopes="")
