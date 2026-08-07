from asgiref.sync import async_to_sync
from django.db.models import QuerySet
from django.test import SimpleTestCase, TestCase

from core.services import Environment
from user.models import User, UserRole
from user.schemas import UserCreateSchema, UserUpdateSchema
from user.services import UserRoleService, UserService

# Valid UUID that matches no record: `User.pk` is a UUIDField, so an
# ill-typed pk would raise a raw django ValidationError instead of simply
# not matching. Coercing pks is part of step 5.
UNKNOWN_PK = "00000000-0000-4000-8000-000000000000"


class TestServiceComposition(SimpleTestCase):
    """Each generic parameter is materialized by the class that owns it."""

    def test_model_comes_from_the_base(self):
        self.assertIs(UserService.model, User)
        self.assertIs(UserRoleService.model, UserRole)

    def test_every_mixin_hook_runs(self):
        """The regression test for the cooperative `super()` rule.

        Python only calls the closest `__init_subclass__` in the MRO. If any mixin
        forgot its `super().__init_subclass__()` call, the hooks after it would never
        run and their schema would silently be missing -- the quietest possible bug
        in this structure. Reading all three attributes at once locks the chain.
        """
        self.assertIs(UserService.create_schema, UserCreateSchema)
        self.assertIs(UserService.update_schema, UserUpdateSchema)
        self.assertIs(UserService.model, User)

    def test_attributes_are_readable_without_instantiating(self):
        """They are class attributes, not properties: usable before any env exists."""
        self.assertIsNotNone(UserService.__dict__.get("model") or UserService.model)
        self.assertTrue(hasattr(UserService, "create_schema"))

    def test_composition_is_opt_in(self):
        """A read-only service exposes no write operation at all."""
        self.assertFalse(hasattr(UserRoleService, "create"))
        self.assertFalse(hasattr(UserRoleService, "update"))
        self.assertFalse(hasattr(UserRoleService, "delete"))
        self.assertTrue(hasattr(UserRoleService, "read"))

    def test_browse_is_available_whatever_the_composition(self):
        """`browse` is owed to the other services, so it lives on the base class.

        `UserRoleService` exposes no write surface but must still be browsable, since
        `UserService` resolves its `roles` relation through it.
        """
        self.assertTrue(hasattr(UserRoleService, "browse"))
        self.assertTrue(hasattr(UserService, "browse"))


class TestBrowse(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.own_profile_role = UserRole.objects.create(
            id="BROWSE_OWN", name="Own profile only", rules=["user_manage_own_profile"]
        )
        cls.tintin = User.objects.create(
            username="tintin", email="tintin@moulinsart.com"
        )
        cls.haddock = User.objects.create(
            username="haddock", email="haddock@moulinsart.com"
        )

    def browse(self, user, pks):
        service = Environment(user=user).get(UserService)
        return async_to_sync(service.browse)(pks)

    def test_returns_an_unevaluated_queryset(self):
        result = self.browse(self.tintin, [self.tintin.pk])

        self.assertIsInstance(result, QuerySet)
        self.assertIsNone(result._result_cache)

    def test_returns_the_requested_records(self):
        result = self.browse(self.tintin, [self.tintin.pk, self.haddock.pk])

        self.assertEqual(
            {obj.pk for obj in result}, {self.tintin.pk, self.haddock.pk}
        )

    def test_missing_pk_is_absent_but_does_not_raise(self):
        """The caller compares asked-for with obtained; `browse` itself stays silent."""
        result = self.browse(self.tintin, [self.tintin.pk, UNKNOWN_PK])

        self.assertEqual({obj.pk for obj in result}, {self.tintin.pk})

    def test_access_rules_scope_the_result(self):
        self.tintin.roles.set([self.own_profile_role])

        result = self.browse(self.tintin, [self.tintin.pk, self.haddock.pk])

        self.assertEqual({obj.pk for obj in result}, {self.tintin.pk})

    def test_forbidden_and_missing_are_indistinguishable(self):
        """Both yield an empty result, so no existence is leaked."""
        self.tintin.roles.set([self.own_profile_role])

        forbidden = self.browse(self.tintin, [self.haddock.pk])
        missing = self.browse(self.tintin, [UNKNOWN_PK])

        self.assertEqual(list(forbidden), list(missing))

    def test_caller_can_only_narrow_the_result(self):
        """Rules are baked in as Q objects, so chaining cannot widen the scope."""
        self.tintin.roles.set([self.own_profile_role])

        result = self.browse(self.tintin, [self.tintin.pk, self.haddock.pk]).filter(
            username="haddock"
        )

        self.assertEqual(list(result), [])
