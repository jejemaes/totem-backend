from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from user.schemas import UserCreateSchema, UserUpdateSchema


class UserSchemaTest(SimpleTestCase):
    """ Field-level validation happens when the schema is built, for every caller
    and not only the HTTP one: the service never sees these values. """

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("email malformed", {"login": "pipin", "email": "not-an-email", "roles": []}, "email"),
            ("user type not a choice", {"login": "pipin", "email": "pipin@lacomte.com", "roles": [], "user_type": "HOBBIT"}, "user_type"),
            ("language not a choice", {"login": "pipin", "email": "pipin@lacomte.com", "roles": [], "language": "elvish"}, "language"),
            ("email missing", {"login": "pipin", "roles": []}, "email"),
            ("login missing", {"email": "pipin@lacomte.com", "roles": []}, "login"),
            # `username` is renamed on the wire: only `login` is accepted.
            ("orm name refused", {"username": "pipin", "email": "pipin@lacomte.com", "roles": []}, "login"),
        ]
    )
    def test_create_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            UserCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_create_schema_valid(self):
        data = UserCreateSchema(login="pipin", email="pipin@lacomte.com", roles=["FELLOWSHIP_HOBBIT"])

        self.assertEqual((data.username, data.email, data.roles), ("pipin", "pipin@lacomte.com", ["FELLOWSHIP_HOBBIT"]))

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_update_schema_every_field_is_optional(self):
        self.assertEqual(UserUpdateSchema().model_fields_set, set())

    @parameterized.expand(
        [
            ("email malformed", {"email": "not-an-email"}, "email"),
            ("user type not a choice", {"user_type": "HOBBIT"}, "user_type"),
        ]
    )
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            UserUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_orm_name_ignored(self):
        # Ignored rather than refused: an update schema forbids nothing, but
        # `username` is not one of its names.
        self.assertEqual(UserUpdateSchema(username="pipin").model_fields_set, set())

    @parameterized.expand([(UserCreateSchema,), (UserUpdateSchema,)])
    def test_password_is_on_no_write_schema(self, schema):
        # Hashed and validated by dedicated operations, never written as is.
        self.assertNotIn("password", schema.model_fields)
