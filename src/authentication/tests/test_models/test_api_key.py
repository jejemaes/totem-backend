from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from authentication.models import ApiKey
from authentication.tokens import hash_secret


@freeze_time("2024-11-18 11:12:13")
class TestApiKeyQuerySet(TestCase):

    # ---------------------------------------------------------
    # create_with_secret
    # ---------------------------------------------------------

    def test_create_with_secret_returns_the_clear_text_once(self):
        key, secret = ApiKey.objects.create_with_secret("Reporting", ["totem.user.read"])

        self.assertEqual(key.secret_hash, hash_secret(secret))
        self.assertNotEqual(key.secret_hash, secret)
        # Reloaded from the database, the clear secret is gone for good.
        self.assertIsNone(ApiKey.objects.get(pk=key.pk).secret)

    def test_scope_is_whatever_was_asked_for(self):
        key, dummy = ApiKey.objects.create_with_secret("Reporting", ["totem.user.read"])
        self.assertEqual(key.scope, ["totem.user.read"])

    def test_a_key_can_be_created_with_no_scope_at_all(self):
        # `scope` is mandatory but may be empty: granting nothing is a choice the
        # caller states, never a default that happens to them.
        key, dummy = ApiKey.objects.create_with_secret("Useless", [])
        self.assertEqual(key.scope, [])
        self.assertEqual(key.scopes, set())

    def test_secret_hash_is_unique(self):
        key, secret = ApiKey.objects.create_with_secret("First", [])
        with self.assertRaises(IntegrityError):
            ApiKey.objects.create(name="Second", secret_hash=key.secret_hash, scope=[])

    def test_name_is_unique(self):
        ApiKey.objects.create_with_secret("Reporting", [])
        with self.assertRaises(IntegrityError):
            ApiKey.objects.create_with_secret("Reporting", [])

    def test_bulk_create_keeps_an_explicit_hash(self):
        # The escape hatch the derivation leaves open, and the only way a caller
        # can provide a secret it already holds.
        given = hash_secret("a-secret-of-my-own")
        ApiKey.objects.bulk_create([ApiKey(name="Imported", secret_hash=given, scope=[])])
        self.assertEqual(ApiKey.objects.get(name="Imported").secret_hash, given)

    # ---------------------------------------------------------
    # usable
    # ---------------------------------------------------------

    def test_usable_keeps_a_key_without_expiry(self):
        key, dummy = ApiKey.objects.create_with_secret("Forever", [])
        self.assertEqual([k.pk for k in ApiKey.objects.usable()], [key.pk])

    def test_usable_excludes_inactive_and_expired(self):
        live, dummy = ApiKey.objects.create_with_secret(
            "Live", [], expires_at=timezone.now() + timedelta(days=1)
        )
        inactive, dummy = ApiKey.objects.create_with_secret("Inactive", [], is_active=False)
        expired, dummy = ApiKey.objects.create_with_secret(
            "Expired", [], expires_at=timezone.now()
        )

        self.assertEqual([k.pk for k in ApiKey.objects.usable()], [live.pk])

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def test_an_unregistered_scope_is_refused(self):
        key = ApiKey(name="Bogus", scope=["totem.nothing.read"], secret_hash=hash_secret("x"))
        with self.assertRaises(ValidationError):
            key.full_clean()

    def test_a_non_public_scope_is_refused(self):
        # `totem.apikey.*` is registered with `is_public=False` precisely so that a
        # key cannot be granted the right to mint keys.
        key = ApiKey(name="Bogus", scope=["totem.apikey.create"], secret_hash=hash_secret("x"))
        with self.assertRaises(ValidationError):
            key.full_clean()

    def test_duplicated_scopes_are_refused(self):
        key = ApiKey(
            name="Bogus",
            scope=["totem.user.read", "totem.user.read"],
            secret_hash=hash_secret("x"),
        )
        with self.assertRaises(ValidationError):
            key.full_clean()

    # ---------------------------------------------------------
    # The `request.auth` contract
    # ---------------------------------------------------------

    def test_a_key_is_an_authenticated_principal_without_a_user(self):
        key, dummy = ApiKey.objects.create_with_secret("Reporting", ["totem.user.read"])

        self.assertTrue(key.is_authenticated)
        self.assertIsNone(key.user)
        self.assertEqual(key.scopes, {"totem.user.read"})

    def test_has_scopes(self):
        key, dummy = ApiKey.objects.create_with_secret(
            "Reporting", ["totem.user.read", "totem.contact.read"]
        )

        self.assertTrue(key.has_scopes([]))  # a route asking for none asks only for auth
        self.assertTrue(key.has_scopes(["totem.user.read"]))
        self.assertTrue(key.has_scopes(["totem.user.read", "totem.contact.read"]))
        self.assertFalse(key.has_scopes(["totem.user.delete"]))
        self.assertFalse(key.has_scopes(["totem.user.read", "totem.user.delete"]))

    def test_a_key_without_scope_grants_nothing_but_authentication(self):
        key, dummy = ApiKey.objects.create_with_secret("Useless", [])

        self.assertTrue(key.has_scopes([]))
        self.assertFalse(key.has_scopes(["totem.user.read"]))
