import typing as t
from unittest.mock import patch

import pydantic
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import AliasChoices

from core.api.validation import validate_controllers
from core.schemas import create_schema
from user.api.users import UserController
from user.models import User


class TestControllerValidation(SimpleTestCase):
    """Controller/service consistency, checked at startup rather than on first
    request. Same philosophy as `ServiceRegistry.validate`: everything asserted
    here would otherwise fail -- or pass silently -- deep inside a request."""

    def test_current_configuration_is_valid(self):
        validate_controllers()  # must not raise

    def test_request_schema_field_unknown_to_the_service_is_rejected(self):
        """`_input_values` extracts along the service schema: a field it does not
        declare is silently dropped from every payload. Must fail at startup."""
        schema = create_schema(
            User, name="TestUpdateWithIsActive", fields=["username", "is_active"],
            optional_fields="__all__",
            extra_fields_kwargs={"username": {"validation_alias": "login"}},
        )

        with patch.object(UserController, "update_request_schema", schema):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                validate_controllers()

        self.assertIn("is_active", str(ctx.exception))
        self.assertIn("silently drop", str(ctx.exception))

    def test_response_style_alias_on_a_request_schema_is_rejected(self):
        """`alias` keeps the Django field name accepted on input (it has to, for
        response schemas to read ORM data): on a request schema that would let an
        undocumented name into the body contract."""
        schema = create_schema(
            User, name="TestCreateWithResponseAlias",
            fields=["username", "email", "roles"],
            extra_fields_kwargs={"username": {"alias": "login"}},
        )

        with patch.object(UserController, "create_request_schema", schema):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                validate_controllers()

        self.assertIn("response-style", str(ctx.exception))

    def test_lax_rename_on_a_request_schema_is_rejected(self):
        "A hand-built AliasChoices accepting both names is the same laxity."
        schema = pydantic.create_model(
            "TestLaxCreateInput",
            username=(
                t.Optional[str],
                pydantic.Field(
                    default=None,
                    validation_alias=AliasChoices("login", "username"),
                ),
            ),
        )

        with patch.object(UserController, "create_request_schema", schema):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                validate_controllers()

        self.assertIn("both its public name and the Django field name", str(ctx.exception))

    def test_unreadable_rename_on_a_response_schema_is_rejected(self):
        """A bare `validation_alias` on a response schema makes pydantic look up
        the alias on ORM instances, where only the Django field name exists: the
        field would silently disappear from responses."""
        schema = pydantic.create_model(
            "TestStrictResponse",
            username=(
                t.Optional[str],
                pydantic.Field(default=None, validation_alias="login"),
            ),
        )

        with patch.object(UserController, "retrieve_response_schema", schema):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                validate_controllers()

        self.assertIn("silently disappear", str(ctx.exception))

    def test_list_response_schema_annotation_is_unwrapped(self):
        schema = pydantic.create_model(
            "TestStrictListResponse",
            username=(
                t.Optional[str],
                pydantic.Field(default=None, validation_alias="login"),
            ),
        )

        with patch.object(UserController, "list_response_schema", t.List[schema]):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                validate_controllers()

        self.assertIn("TestStrictListResponse", str(ctx.exception))

    @parameterized.expand(
        [
            ("well placed", True, ["create", "default_values", "retrieve", "update", "delete"], None),
            # The create mixin behind `BaseController` in the MRO: never registered.
            ("never registered", True, ["retrieve", "update", "delete"], "registers no /default-values/ route"),
            # The create mixin after the retrieve one, as `ModelController` once had it.
            ("after /{id}/", True, ["retrieve", "create", "default_values"], "registered after the /{id}/ routes (retrieve)"),
            # The mixin inherited without a creation body: no route is expected.
            ("no creation", False, ["retrieve"], None),
        ]
    )
    def test_default_values_route_order(self, dummy, creates, routes, message):
        """On stand-ins, as `ResequenceDeclarationTest.test_route_order`: the routes
        a controller registers land in its `__dict__` in registration order."""
        from core.api import CreateModelControllerMixin
        from core.api.validation import _check_default_values_route

        controller = type(
            "StandInController", (CreateModelControllerMixin,),
            {
                "model": User,
                "create_request_schema": UserController.create_request_schema if creates else None,
                **{name: lambda self: None for name in routes},
            },
        )
        errors = list(_check_default_values_route(controller))

        if message is None:
            self.assertEqual(errors, [])
        else:
            self.assertEqual(len(errors), 1)
            self.assertIn(message, errors[0])
