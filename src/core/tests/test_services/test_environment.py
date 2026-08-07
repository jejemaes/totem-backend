from asgiref.sync import async_to_sync
from django.test import TestCase

from core.services import Environment
from user.models import User, UserRole
from user.services import UserRoleService, UserService


class TestEnvironment(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.role = UserRole.objects.create(id="ENV_TEST", name="Role Env Test")
        cls.user = User.objects.create(
            username="milou", email="milou@moulinsart.com", password="B0ne4ever"
        )
        cls.user.roles.set([cls.role])

    #
    # Service access
    #

    def test_getitem_returns_the_service_of_the_model(self):
        env = Environment(user=self.user)

        self.assertIsInstance(env[User], UserService)
        self.assertIsInstance(env[UserRole], UserRoleService)

    def test_getitem_on_unserved_model_raises(self):
        env = Environment(user=self.user)

        with self.assertRaises(KeyError):
            env[UserRole.users.through]  # the m2m through model has no service

    def test_get_returns_the_same_instance_within_an_environment(self):
        """Lazy but cached: one instance per service per unit of work."""
        env = Environment(user=self.user)

        self.assertIs(env.get(UserService), env.get(UserService))
        self.assertIs(env[User], env.get(UserService))

    def test_each_environment_builds_its_own_services(self):
        self.assertIsNot(
            Environment(user=self.user).get(UserService),
            Environment(user=self.user).get(UserService),
        )

    def test_contains_and_iteration_expose_served_models(self):
        env = Environment(user=self.user)

        self.assertIn(User, env)
        self.assertIn(UserRole, env)
        self.assertIn(User, list(env))
        self.assertEqual(len(env), len(list(env)))

    #
    # Isolation between environments
    #

    def test_environments_are_never_deduplicated(self):
        """Two environments with identical values must stay distinct objects.

        They used to be deduplicated in a process-wide WeakSet, which made two
        concurrent requests of the same user share one instance -- and with it a
        mutable context and, now, a memoized access cache.
        """
        self.assertIsNot(Environment(user=self.user), Environment(user=self.user))

    def test_context_cannot_be_mutated(self):
        env = Environment(user=self.user, context={"lang_hint": "fr"})

        with self.assertRaises(TypeError):
            env.context["lang_hint"] = "en"

    def test_public_attributes_are_read_only(self):
        env = Environment(user=self.user)

        with self.assertRaises(AttributeError):
            env.user = None

    #
    # Deriving a new environment
    #

    def test_call_keeps_current_values_as_defaults(self):
        env = Environment(user=self.user, language="fr-be", context={"a": 1})

        derived = env(context={"a": 2})

        self.assertEqual(derived.user, self.user)
        self.assertEqual(derived.language, "fr-be")
        self.assertEqual(dict(derived.context), {"a": 2})

    def test_with_context_returns_a_service_on_a_new_environment(self):
        service = Environment(user=self.user).get(UserService)

        derived = service.with_context(dry_run=True)

        self.assertIsNot(derived, service)
        self.assertEqual(derived.env.context["dry_run"], True)
        self.assertNotIn("dry_run", service.env.context)
        self.assertEqual(derived.env.user, self.user)

    #
    # Access rules memoization
    #

    def test_access_roles_are_fetched_once_per_environment(self):
        env = Environment(user=self.user)

        with self.assertNumQueries(1):
            first = async_to_sync(env.get_access_roles)()
            second = async_to_sync(env.get_access_roles)()

        self.assertEqual([r.pk for r in first], [self.role.pk])
        self.assertEqual(first, second)

    def test_access_roles_are_not_shared_across_environments(self):
        with self.assertNumQueries(1):
            async_to_sync(Environment(user=self.user).get_access_roles)()
        with self.assertNumQueries(1):
            async_to_sync(Environment(user=self.user).get_access_roles)()

    def test_access_roles_without_user_hits_no_query(self):
        env = Environment()

        with self.assertNumQueries(0):
            self.assertEqual(async_to_sync(env.get_access_roles)(), [])

    def test_empty_roles_are_memoized_too(self):
        """An empty result must not be mistaken for "not computed yet"."""
        user = User.objects.create(
            username="tournesol", email="tournesol@moulinsart.com"
        )
        env = Environment(user=user)

        with self.assertNumQueries(1):
            self.assertEqual(async_to_sync(env.get_access_roles)(), [])
            self.assertEqual(async_to_sync(env.get_access_roles)(), [])
