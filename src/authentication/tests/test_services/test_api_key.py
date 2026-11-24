from datetime import datetime, timezone as dt_timezone

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from authentication.models import ApiKey, RefreshToken
from authentication.schemas import ApiKeyCreateSchema, ApiKeyFilterSchema
from authentication.services import ApiKeyService
from authentication.tokens import hash_secret
from core.testing import ServiceTestCaseMixin

from authentication.tests.test_services.common_api_key import (
    KEY_ARCHIVE_ID,
    KEY_PALANTIR_ID,
    KEY_UNKNOWN_ID,
    ApiKeyServiceCommonMixin,
)

EXPIRES_AT = datetime(2030, 1, 1, tzinfo=dt_timezone.utc)


class ApiKeyServiceTest(ApiKeyServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `ApiKeyService`: create, read, delete. The secret is derived by
    `ApiKeyQuerySet.bulk_create`, returned once, and never stored in clear.

    No access rules tests: no `BaseRule` is registered for `ApiKey`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(ApiKeyService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("with a scope", {"name": "Shire Census", "scope": ["totem.user.read"]}, {"scope": ["totem.user.read"], "expires_at": None}),
            # Empty by default: a new key can do nothing.
            ("without scope", {"name": "Shire Census"}, {"scope": []}),
            ("with an expiry", {"name": "Shire Census", "scope": [], "expires_at": EXPIRES_AT}, {"expires_at": EXPIRES_AT}),
        ]
    )
    def test_create(self, label, payload, expected_values):
        # The roles, the transaction, the insert, and the access rules checked
        # on the rows written.
        with self.assertNumQueries(5):
            instances = async_to_sync(self.service.create)([ApiKeyCreateSchema(**payload)])

        key = instances[0]
        # Set by `ApiKeyQuerySet.bulk_create`, the only moment it exists in clear,
        # and kept for the controller, which refetches the record.
        self.assertIsNotNone(key.secret)
        self.assertEqual(self.service.minted_secret(key.pk), key.secret)
        stored = ApiKey.objects.get(pk=key.pk)
        self.assertEqual((stored.name, stored.is_active, stored.secret_hash), ("Shire Census", True, hash_secret(key.secret)))
        self.assertEqual({name: getattr(stored, name) for name in expected_values}, expected_values)
        self.assertIsNone(stored.secret)

    # No `test_create_invalid`: the one rule, a registered public scope, is the
    # `choices` of the field, refused when the schema is built -- see
    # `test_schemas.test_api_key`. A `validate_data` would be dead code.

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"name": "Shire Census", "scope": []}])

        self.assertEqual(ApiKey.objects.count(), 2)

    # No `test_create_relations`: a key has no relation to write.

    def test_create_batch(self):
        with self.assertNumQueries(5):
            instances = async_to_sync(self.service.create)(
                [ApiKeyCreateSchema(name="First", scope=[]), ApiKeyCreateSchema(name="Second", scope=[])]
            )

        # Each key gets its own secret.
        self.assertNotEqual(instances[0].secret, instances[1].secret)
        self.assertEqual(
            {key.name: key.secret_hash for key in ApiKey.objects.filter(name__in=["First", "Second"])},
            {"First": hash_secret(instances[0].secret), "Second": hash_secret(instances[1].secret)},
        )

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(None)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, {"scope": []})

    @parameterized.expand([("update",), ("resequence",)])
    def test_operation_is_not_composed(self, operation):
        # A secret is revoked and replaced, never edited, and widening the scopes
        # of a key in circulation would be a silent privilege escalation.
        self.assertFalse(hasattr(ApiKeyService, operation))

    def test_refresh_tokens_have_no_service(self):
        # Registering one would hand a table of credentials to generic code, and
        # a model without rule is readable by anyone.
        env = self.service.env
        self.assertNotIn(RefreshToken, env)
        with self.assertRaises(KeyError):
            env[RefreshToken]

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, [KEY_ARCHIVE_ID, KEY_PALANTIR_ID]),
            # The filter schema of the API.
            ("the active ones", ApiKeyFilterSchema(is_active=True), [KEY_ARCHIVE_ID]),
            ("the revoked ones", ApiKeyFilterSchema(is_active=False), [KEY_PALANTIR_ID]),
            ("by name", ApiKeyFilterSchema(name="book"), [KEY_ARCHIVE_ID]),
            ("nothing matches", ApiKeyFilterSchema(name="Mordor"), []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            keys = list(async_to_sync(self.service.read)(filters))

        self.assertCountEqual([key.pk for key in keys], expected_pks)
        # A read never exposes a usable credential: the secret lives only on the
        # instance a creation returned.
        self.assertTrue(all(key.secret is None for key in keys))

    @parameterized.expand(
        [
            ("by name", ["name"], [KEY_PALANTIR_ID, KEY_ARCHIVE_ID]),
            ("by state, descending", ["-is_active"], [KEY_ARCHIVE_ID, KEY_PALANTIR_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [key.pk for key in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    def test_read_fields(self):
        with self.assertNumQueries(2):
            keys = list(async_to_sync(self.service.read)({"id": KEY_ARCHIVE_ID}, fields=["id", "name", "scope"]))

        self.assertEqual([(key.name, key.scope) for key in keys], [("Red Book Archive", ["totem.user.read"])])
        self.assertIn("secret_hash", keys[0].get_deferred_fields())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a key", {"id": KEY_ARCHIVE_ID}, 1),
            ("the revoked ones", {"is_active": False}, 1),
            ("nothing matches", {"id": KEY_UNKNOWN_ID}, 0),
        ]
    )
    def test_delete(self, label, filters, affected):
        # The roles, the transaction, and one DELETE: nothing points at a key,
        # so django deletes it without reading it first.
        with self.assertNumQueries(4):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(ApiKey.objects.count(), 2 - affected)
        self.assertFalse(ApiKey.objects.filter(**filters).exists())

    # ------------------------------------------
    # Minted Secret
    # ------------------------------------------

    @parameterized.expand(
        [
            # Bulk created outside this unit of work: its secret is gone.
            ("a key of the data", KEY_ARCHIVE_ID),
            ("an unknown key", KEY_UNKNOWN_ID),
        ]
    )
    def test_minted_secret_unknown(self, label, pk):
        self.assertIsNone(self.service.minted_secret(pk))

    def test_minted_secret_is_scoped_to_the_environment(self):
        # Request-scoped: another environment never sees the secrets of this one.
        key = async_to_sync(self.service.create)([ApiKeyCreateSchema(name="Shire Census", scope=[])])[0]

        self.assertIsNone(self.get_service(ApiKeyService, user=self.user_frodon).minted_secret(key.pk))
