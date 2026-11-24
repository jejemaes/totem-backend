from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from authentication.schemas import ApiKeyCreateSchema
from user.access_rights import get_public_permission


class ApiKeySchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("name missing", {"scope": []}, "name"),
            # The `choices` of the array's base field become a pydantic enum: a
            # bad scope never reaches `to_internal_values`, which is why a
            # `validate_data` for it would be dead code.
            ("an unregistered scope", {"name": "Bogus", "scope": ["totem.nothing.read"]}, "scope"),
            # A key able to mint keys would be a privilege escalation: the
            # non-public permissions are not offered.
            ("a non-public scope", {"name": "Bogus", "scope": ["totem.apikey.create"]}, "scope"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            ApiKeyCreateSchema(**payload)

        self.assertEqual({error["loc"][0] for error in ctx.exception.errors()}, {field})

    def test_create_schema_offers_every_public_scope(self):
        # The safe side of the "choices read too early" trap: the permission
        # registry is filled by `UserConfig.ready()`, before `CoreConfig.ready()`
        # imports the services and builds this schema.
        for permission, dummy in get_public_permission():
            with self.subTest(permission=permission):
                self.assertEqual(ApiKeyCreateSchema(name="Fine", scope=[permission]).scope, [permission])
