from asgiref.sync import async_to_sync
from django.db.models import Q
from django.test import TestCase

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from user.access_policy import BaseRule
from user.models import User, UserRole
from user.schemas import UserCreateSchema
from user.services import UserService


class VisibleRolesOnlyRule(BaseRule):
    """Test rule scoping `UserRole`, of which the project declares none.

    Registering it is harmless for the rest of the suite: a rule only applies to
    users whose roles reference its identifier, and no fixture outside this module
    does.
    """

    identifier: str = "test_visible_roles_only"
    model = UserRole
    name = "Visible roles only"
    operations = ["read"]

    def scope_filter(self, context) -> Q:
        return Q(id__startswith="VISIBLE")


class TestRelationResolutionIsScoped(TestCase):
    """Relations resolve through the related service, so its access rules apply.

    This is what closes the leak of the previous implementation, which resolved
    relations with `related_model.objects.filter(pk__in=...)` and therefore accepted
    records the acting user had no right to see.
    """

    @classmethod
    def setUpTestData(cls):
        cls.visible_role = UserRole.objects.create(
            id="VISIBLE_ROLE", name="Visible role"
        )
        cls.hidden_role = UserRole.objects.create(id="HIDDEN_ROLE", name="Hidden role")
        cls.scoped_role = UserRole.objects.create(
            id="VISIBLE_SCOPING",
            name="Grants the scoping rule",
            rules=["test_visible_roles_only"],
        )
        cls.actor = User.objects.create(
            username="tintin", email="tintin@moulinsart.com"
        )
        cls.actor.roles.set([cls.scoped_role])

    def create_with_roles(self, roles):
        service = Environment(user=self.actor).get(UserService)
        data = UserCreateSchema(
            login="haddock", email="haddock@moulinsart.com", roles=roles
        )
        return async_to_sync(service.create)([data])

    def message_for(self, roles):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.create_with_roles(roles)
        return ctx.exception.dict()

    def test_visible_relation_is_accepted(self):
        instances = self.create_with_roles(["VISIBLE_ROLE"])

        self.assertEqual(
            [role.pk for role in instances[0].roles.all()], [self.visible_role.pk]
        )

    def test_relation_out_of_scope_is_rejected(self):
        """The record exists, but the acting user may not see it."""
        self.assertTrue(UserRole.objects.filter(pk="HIDDEN_ROLE").exists())

        self.message_for(["HIDDEN_ROLE"])

        self.assertFalse(User.objects.filter(username="haddock").exists())

    def test_out_of_scope_and_unknown_are_indistinguishable(self):
        """Same error either way, so no existence is leaked."""
        hidden = self.message_for(["HIDDEN_ROLE"])
        unknown = self.message_for(["NOT_EXISTING"])

        self.assertEqual(
            list(hidden.values())[0].keys(), list(unknown.values())[0].keys()
        )
        self.assertEqual(
            [msg.replace("HIDDEN_ROLE", "X") for msg in str(hidden).split()],
            [msg.replace("NOT_EXISTING", "X") for msg in str(unknown).split()],
        )

    def test_relation_without_a_service_raises(self):
        """No silent fallback to the model manager.

        Falling back would resolve that relation with no access rules at all, which
        is the very hole this step closes. `groups`, inherited from `AbstractUser`,
        is a real case: it has no service and is deliberately absent from the input
        schemas, so it is never reached in practice.
        """
        service = Environment(user=self.actor).get(UserService)

        with self.assertRaises(KeyError):
            async_to_sync(service._resolve_relation)(
                User._meta.get_field("groups"), [1]
            )

    def test_pk_is_coerced_before_being_matched(self):
        """The generated schemas type m2m pks as `str` whatever the real pk field.

        Without coercion the lookup would return the record but the comparison
        against the payload value would miss it, reporting a valid relation as
        invalid. The result stays keyed by the value the caller passed.
        """
        UserRole.objects.create(id="123", name="Numeric-looking id")
        # An actor with no scoping rule, so the resolution is not narrowed here.
        actor = User.objects.create(username="nestor", email="nestor@moulinsart.com")
        service = Environment(user=actor).get(UserService)

        resolved = async_to_sync(service._resolve_relation)(
            User._meta.get_field("roles"), [123]
        )

        self.assertEqual(list(resolved), [123])
        self.assertEqual(resolved[123].pk, "123")
