"""Public renames (aliases) on generated schemas.

A field can be exposed to the API under another name than its Django field name,
DRF-style, through `Meta.extra_fields_kwargs`. The pydantic field name always
stays the Django field name -- services, querysets and the factory key on it --
only the JSON surface changes. Two declarations exist (see `ExtraFieldInfos`):

* `alias` for response schemas: serializes under the public name, still readable
  from ORM instances and ORM-keyed dicts;
* `validation_alias` for request-body schemas: the body accepts ONLY the public
  name.
"""

import typing as t

from django.test import SimpleTestCase
from ninja.errors import ConfigError
from pydantic import ValidationError as PydanticValidationError

from core.schemas import ModelSchema, create_schema
from core.schemas.utils import (
    extract_orm_fields_map,
    schema_orm_to_public_fields,
    schema_public_to_orm_fields,
)
from user.models import User, UserRoleRelation


class UserAliasedSchema(ModelSchema):
    "Response-style schema: `username` is exposed as `login`."

    class Meta:
        model = User
        fields = ["id", "username", "email"]
        optional_fields = "__all__"
        extra_fields_kwargs = {
            "username": {"alias": "login"},
        }


class UserStrictInputSchema(ModelSchema):
    "Request-body-style schema: only `login` is accepted on input."

    class Meta:
        model = User
        fields = ["username", "email"]
        optional_fields = ["email"]
        extra_fields_kwargs = {
            "username": {"validation_alias": "login"},
        }


class TestResponseAlias(SimpleTestCase):
    "`alias`: public on the way out, permissive on the way in."

    def test_field_name_stays_the_django_field_name(self):
        self.assertIn("username", UserAliasedSchema.model_fields)
        self.assertNotIn("login", UserAliasedSchema.model_fields)

    def test_validates_from_public_name_and_from_orm_name(self):
        "Both the alias and the Django field name populate the same field."
        for payload in ({"login": "bob"}, {"username": "bob"}):
            schema = UserAliasedSchema.model_validate(payload)
            self.assertEqual(schema.username, "bob")
            # `model_fields_set` speaks ORM whatever the input name: this is what
            # keeps `_input_values` and `exclude_unset` working on the service side.
            self.assertIn("username", schema.model_fields_set)

    def test_validates_from_orm_instance_attributes(self):
        "The retrieve/create/update routes serialize django instances."
        instance = User(username="bob", email="bob@x.com")
        schema = UserAliasedSchema.model_validate(instance, from_attributes=True)
        self.assertEqual(schema.username, "bob")

    def test_serializes_under_the_public_name(self):
        schema = UserAliasedSchema.model_validate({"username": "bob"})
        self.assertEqual(
            schema.model_dump(by_alias=True, exclude_unset=True), {"login": "bob"}
        )
        # without `by_alias`, the internal name: routes always serialize by_alias
        self.assertEqual(
            schema.model_dump(exclude_unset=True), {"username": "bob"}
        )

    def test_openapi_exposes_the_public_name(self):
        for mode in ("validation", "serialization"):
            properties = UserAliasedSchema.model_json_schema(mode=mode)["properties"]
            self.assertIn("login", properties)
            self.assertNotIn("username", properties)

    def test_unset_fields_stay_unset(self):
        "The list route relies on `exclude_unset` over partial ORM dicts (`?fields=`)."
        schema = UserAliasedSchema.model_validate({"email": "bob@x.com"})
        self.assertEqual(
            schema.model_dump(by_alias=True, exclude_unset=True),
            {"email": "bob@x.com"},
        )


class TestStrictInputAlias(SimpleTestCase):
    "`validation_alias`: the ORM name is not part of the wire contract."

    def test_accepts_only_the_public_name(self):
        schema = UserStrictInputSchema(login="bob")
        self.assertEqual(schema.username, "bob")

        with self.assertRaises(PydanticValidationError) as ctx:
            UserStrictInputSchema(username="bob")
        # the missing-field error points at the public name
        self.assertIn("login", str(ctx.exception))

    def test_openapi_exposes_the_public_name(self):
        properties = UserStrictInputSchema.model_json_schema(mode="validation")[
            "properties"
        ]
        self.assertIn("login", properties)
        self.assertNotIn("username", properties)

    def test_service_reads_the_orm_name(self):
        "`_input_values` does `getattr(data, <django field name>)`."
        schema = UserStrictInputSchema(login="bob")
        self.assertEqual(getattr(schema, "username"), "bob")
        self.assertEqual(schema.model_fields_set, {"username"})


class TestAliasDeclaration(SimpleTestCase):

    def test_alias_and_validation_alias_are_exclusive(self):
        with self.assertRaises(ConfigError):
            create_schema(
                User,
                name="UserBothAliases",
                fields=["username"],
                extra_fields_kwargs={
                    "username": {"alias": "login", "validation_alias": "login"}
                },
            )

    def test_factory_cache_discriminates_on_extra_fields_kwargs(self):
        "Same model/name/fields but different aliases must not share a schema."
        plain = create_schema(User, name="UserCacheProbe", fields=["username"])
        aliased = create_schema(
            User,
            name="UserCacheProbe",
            fields=["username"],
            extra_fields_kwargs={"username": {"alias": "login"}},
        )
        self.assertIsNot(plain, aliased)
        self.assertIsNone(plain.model_fields["username"].serialization_alias)
        self.assertEqual(
            aliased.model_fields["username"].serialization_alias, "login"
        )


class TestForeignKeyAlias(SimpleTestCase):

    def test_fk_accepts_public_name_orm_name_and_attname(self):
        """The list route feeds the schema with `instance.__dict__` dicts, where a
        FK lives under its `attname` (`role_id`), not its field name (`role`)."""
        schema_class = create_schema(
            UserRoleRelation,
            name="RoleRelationAliased",
            fields=["role"],
            optional_fields="__all__",
            extra_fields_kwargs={"role": {"alias": "role_ref"}},
        )
        for payload in (
            {"role_ref": "CAT1_TEST1"},
            {"role": "CAT1_TEST1"},
            {"role_id": "CAT1_TEST1"},
        ):
            schema = schema_class.model_validate(payload)
            self.assertEqual(
                schema.model_dump(by_alias=True, exclude_unset=True),
                {"role_ref": "CAT1_TEST1"},
            )


class TestPublicOrmMaps(SimpleTestCase):
    "The translation tables used by `?fields=`, `?ordering=` and error locations."

    def test_public_to_orm(self):
        self.assertEqual(
            schema_public_to_orm_fields(UserAliasedSchema, User),
            {"id": "id", "login": "username", "email": "email"},
        )

    def test_orm_to_public(self):
        self.assertEqual(
            schema_orm_to_public_fields(UserAliasedSchema, User),
            {"id": "id", "username": "login", "email": "email"},
        )

    def test_list_annotation_is_unwrapped(self):
        self.assertEqual(
            schema_public_to_orm_fields(t.List[UserAliasedSchema], User),
            {"id": "id", "login": "username", "email": "email"},
        )

    def test_orm_fields_map_keys_stay_field_names_for_aliased_relations(self):
        "Regression: an aliased relational field used to KeyError during extraction."
        schema_class = create_schema(
            User,
            name="UserAliasedRelation",
            fields=["username", "roles"],
            optional_fields="__all__",
            extra_fields_kwargs={"roles": {"alias": "granted_roles"}},
        )
        fields_map = extract_orm_fields_map(schema_class, User)
        self.assertEqual(fields_map["roles"]["source"], "roles")
        self.assertEqual(fields_map["roles"]["public"], "granted_roles")
        self.assertEqual(fields_map["username"], {"source": "username", "public": "username"})
