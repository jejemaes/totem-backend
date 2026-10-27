from asgiref.sync import async_to_sync
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from authentication.models import ApiKey, RefreshToken
from authentication.schemas import ApiKeyCreateSchema
from authentication.services import ApiKeyService
from authentication.tokens import hash_secret
from core.services import Environment


class TestApiKeyService(TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(ApiKeyService)

    # ---------------------------------------------------------
    # Composition
    # ---------------------------------------------------------

    def test_a_key_cannot_be_updated(self):
        # The absence of `UpdateMixin` is the guard, so it is what gets asserted:
        # widening the scopes of a key already in circulation would be a silent
        # privilege escalation, and a secret is replaced, never edited.
        self.assertFalse(hasattr(ApiKeyService, "update"))

    def test_refresh_tokens_have_no_service(self):
        # Registering one would hand a table of credentials to generic code --
        # and `ApiKey` aside, a model with no access rule is readable by anyone,
        # since `apply_access_rules` would assemble no lookup for it.
        self.assertNotIn(RefreshToken, self.env)
        with self.assertRaises(KeyError):
            self.env[RefreshToken]

    # ---------------------------------------------------------
    # create
    # ---------------------------------------------------------

    def test_create_derives_the_secret_and_hands_it_back_once(self):
        keys = async_to_sync(self.service.create)(
            [ApiKeyCreateSchema(name="Reporting", scope=["totem.user.read"])]
        )

        key = keys[0]
        self.assertEqual(key.scope, ["totem.user.read"])
        # Set by `ApiKeyQuerySet.bulk_create`, and the only moment it exists.
        self.assertIsNotNone(key.secret)
        self.assertEqual(key.secret_hash, hash_secret(key.secret))
        self.assertIsNone(ApiKey.objects.get(pk=key.pk).secret)

    def test_create_without_scope(self):
        keys = async_to_sync(self.service.create)([ApiKeyCreateSchema(name="Useless", scope=[])])
        self.assertEqual(keys[0].scope, [])

    def test_each_key_gets_its_own_secret(self):
        keys = async_to_sync(self.service.create)(
            [
                ApiKeyCreateSchema(name="First", scope=[]),
                ApiKeyCreateSchema(name="Second", scope=[]),
            ]
        )
        self.assertNotEqual(keys[0].secret, keys[1].secret)
        self.assertNotEqual(keys[0].secret_hash, keys[1].secret_hash)

    def test_an_unregistered_scope_is_refused(self):
        # One layer earlier than a service error: the `choices` of the array's base
        # field become a pydantic enum on the generated schema, so a bad scope
        # never gets as far as `to_internal_values`. Which is also why writing a
        # `validate_data` hook for this would be dead code -- and why, over HTTP,
        # this is a 422 on the body contract rather than a 400 from the service.
        with self.assertRaises(PydanticValidationError):
            ApiKeyCreateSchema(name="Bogus", scope=["totem.nothing.read"])

        self.assertFalse(ApiKey.objects.exists())

    def test_a_non_public_scope_is_refused(self):
        # A key able to mint keys would be a privilege escalation, which is what
        # `is_public=False` on `totem.apikey.*` buys: those are exactly the
        # permissions `ApiKey.scope` does not offer as choices, so they are absent
        # from the enum above.
        with self.assertRaises(PydanticValidationError):
            ApiKeyCreateSchema(name="Bogus", scope=["totem.apikey.create"])

    def test_the_scope_enum_is_complete(self):
        # The safe side of the "choices read too early" trap: the permission
        # registry is filled by `UserConfig.ready()`, while this schema is built
        # when `CoreConfig.ready()` -- last in `INSTALLED_APPS` -- imports
        # `services`. So every public permission really is offered.
        from user.access_rights import get_public_permission

        for permission, dummy in get_public_permission():
            with self.subTest(permission=permission):
                self.assertEqual(
                    ApiKeyCreateSchema(name="Fine", scope=[permission]).scope,
                    [permission],
                )

    # ---------------------------------------------------------
    # read / delete
    # ---------------------------------------------------------

    def test_read_never_exposes_a_usable_credential(self):
        created, secret = ApiKey.objects.create_with_secret("Reporting", ["totem.user.read"])

        keys = list(async_to_sync(self.service.read)())

        self.assertEqual([key.pk for key in keys], [created.pk])
        # `secret` only ever lives on the instance the creation returned.
        self.assertIsNone(keys[0].secret)
        self.assertNotEqual(keys[0].secret_hash, secret)

    def test_delete(self):
        created, dummy = ApiKey.objects.create_with_secret("Reporting", [])

        self.assertEqual(async_to_sync(self.service.delete)({"pk": created.pk}), 1)

        self.assertFalse(ApiKey.objects.exists())
