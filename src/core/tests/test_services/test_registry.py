from unittest.mock import patch

import pydantic
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from core.schemas import create_schema
from core.services import Service, ServiceBase
from core.services.registry import ServiceRegistry
from user.models import User, UserRole
from user.services import UserRoleService, UserService


class TestServiceRegistry(SimpleTestCase):
    """`auth.Group` is the sandbox model on purpose.

    Any *project* model is one service away from breaking these tests --
    `website.Menu` used to sit here and did, the day it got a `MenuService`.
    `auth.Group` is unserved by contract rather than by accident:
    `TestRegistryValidation` below asserts that exposing it for writing must
    fail, and `UserService` deliberately keeps `groups` out of its input
    schemas. Pick another model here only if it carries the same guarantee.
    """

    def tearDown(self):
        super().tearDown()
        # Services declared in a test would otherwise stay registered for the
        # whole process.
        ServiceRegistry._by_model.pop(Group, None)

    def test_services_register_themselves_under_their_model(self):
        self.assertIs(ServiceRegistry.get_service_class(User), UserService)
        self.assertIs(ServiceRegistry.get_service_class(UserRole), UserRoleService)
        self.assertTrue(ServiceRegistry.contains(User))

    def test_declaring_a_service_registers_it(self):
        class GroupService(ServiceBase[Group]):
            pass

        self.assertIs(ServiceRegistry.get_service_class(Group), GroupService)

    def test_service_without_model_is_not_registered(self):
        """Only model-bound services are addressable, the key being the model class."""

        class Plain(Service):
            pass

        self.assertNotIn(Plain, ServiceRegistry._by_model.values())

    def test_unserved_model_resolves_to_none(self):
        self.assertIsNone(ServiceRegistry.get_service_class(Group))
        self.assertFalse(ServiceRegistry.contains(Group))

    def test_two_services_on_the_same_model_raise_at_import(self):
        """Otherwise `env[Model]` would depend on import order."""

        class GroupService(ServiceBase[Group]):
            pass

        with self.assertRaises(ImproperlyConfigured) as ctx:

            class OtherGroupService(ServiceBase[Group]):
                pass

        self.assertIn("single service", str(ctx.exception))
        # The first registration must survive the rejected one.
        self.assertIs(ServiceRegistry.get_service_class(Group), GroupService)

    def test_subclassing_a_concrete_service_is_rejected(self):
        """A model has one service; specializing one would shadow it silently.

        Sharing behaviour between services goes through a model-less base class,
        which is not registered.
        """
        with self.assertRaises(ImproperlyConfigured):

            class SpecializedUserService(UserService):
                pass

    def test_keys_lists_served_models(self):
        self.assertIn(User, ServiceRegistry.keys())
        self.assertIn(UserRole, ServiceRegistry.keys())


class TestRegistryValidation(SimpleTestCase):
    """Cross-service consistency, checked at startup rather than on first request."""

    def test_current_configuration_is_valid(self):
        ServiceRegistry.validate()  # must not raise

    def test_writable_relation_without_a_service_is_rejected(self):
        """`groups` comes from `AbstractUser` and auth.Group has no service.

        It is normally absent from the input schemas, which is exactly why the check
        looks at the schemas and not at `model._meta.get_fields()`. Exposing it for
        writing must fail at startup, not when a payload first carries it.
        """
        schema = create_schema(
            User, name="TestUserWithGroups", fields=["username", "groups"]
        )

        with patch.object(UserService, "create_schema", schema):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                ServiceRegistry.validate()

        self.assertIn("auth.Group", str(ctx.exception))
        self.assertIn("groups", str(ctx.exception))

    def test_schema_field_absent_from_the_model_is_rejected(self):
        schema = pydantic.create_model("TestBogusInput", not_a_field=(str, None))

        with patch.object(UserService, "create_schema", schema):
            with self.assertRaises(ImproperlyConfigured) as ctx:
                ServiceRegistry.validate()

        self.assertIn("not_a_field", str(ctx.exception))

    def test_relation_with_a_service_passes(self):
        """`roles` points at UserRole, which has a service: nothing to report."""
        schema = create_schema(
            User, name="TestUserWithRoles", fields=["username", "roles"]
        )

        with patch.object(UserService, "create_schema", schema):
            ServiceRegistry.validate()  # must not raise
