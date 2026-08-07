from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from core.services import Service, ServiceBase
from core.services.registry import ServiceRegistry
from user.models import User, UserRole
from user.services import UserRoleService, UserService
from website.models import Menu


class TestServiceRegistry(SimpleTestCase):

    def tearDown(self):
        super().tearDown()
        # Services declared in a test would otherwise stay registered for the
        # whole process.
        ServiceRegistry._by_model.pop(Menu, None)

    def test_services_register_themselves_under_their_model(self):
        self.assertIs(ServiceRegistry.get_service_class(User), UserService)
        self.assertIs(ServiceRegistry.get_service_class(UserRole), UserRoleService)
        self.assertTrue(ServiceRegistry.contains(User))

    def test_declaring_a_service_registers_it(self):
        class MenuService(ServiceBase[Menu]):
            pass

        self.assertIs(ServiceRegistry.get_service_class(Menu), MenuService)

    def test_service_without_model_is_not_registered(self):
        """Only model-bound services are addressable, the key being the model class."""

        class Plain(Service):
            pass

        self.assertNotIn(Plain, ServiceRegistry._by_model.values())

    def test_unserved_model_resolves_to_none(self):
        self.assertIsNone(ServiceRegistry.get_service_class(Menu))
        self.assertFalse(ServiceRegistry.contains(Menu))

    def test_two_services_on_the_same_model_raise_at_import(self):
        """Otherwise `env[Model]` would depend on import order."""

        class MenuService(ServiceBase[Menu]):
            pass

        with self.assertRaises(ImproperlyConfigured) as ctx:

            class OtherMenuService(ServiceBase[Menu]):
                pass

        self.assertIn("single service", str(ctx.exception))
        # The first registration must survive the rejected one.
        self.assertIs(ServiceRegistry.get_service_class(Menu), MenuService)

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
