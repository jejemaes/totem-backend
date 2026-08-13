from asgiref.sync import async_to_sync
from django.test import TestCase

from core.services import Environment
from user.models import User
from user.services import UserService


class TestApplyOrdering(TestCase):
    """`ServiceBase.apply_ordering`: a plain list of already-resolved ORM field
    names (`-` prefix for descending). Exercised through `UserService.read`, since
    that's its only caller today; `core.api.ordering.Ordering.ordering_queryset`
    calls it the same way for any other decorated view."""

    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create(
            username="tintin", email="tintin@moulinsart.com", first_name="Tintin"
        )
        User.objects.create(username="haddock", email="haddock@moulinsart.com", first_name="Haddock")
        User.objects.create(username="milou", email="milou@moulinsart.com")  # first_name left null

    @property
    def service(self):
        return Environment(user=self.actor).get(UserService)

    def read(self, ordering):
        return async_to_sync(self.service.read)(ordering=ordering)

    def test_orders_ascending_by_default(self):
        usernames = [u.username for u in self.read(["username"])]
        self.assertEqual(usernames, sorted(usernames))

    def test_dash_prefix_orders_descending(self):
        usernames = [u.username for u in self.read(["-username"])]
        self.assertEqual(usernames, sorted(usernames, reverse=True))

    def test_pk_is_appended_for_determinism(self):
        queryset = self.read(["username"])
        pk_field = queryset.model._meta.pk
        self.assertTrue(
            any(
                getattr(expr, "expression", None) and expr.expression.name == pk_field.name
                for expr in queryset.query.order_by
            )
        )

    def test_nullable_field_sorts_null_last_by_default(self):
        """`UserService` doesn't override `ordering_fields_nulls_last` (`"__all__"`
        by default), so `first_name` (nullable) sorts its nulls last regardless of
        direction -- `milou` (no `first_name`) ends up last either way."""
        ascending = [u.username for u in self.read(["first_name"])]
        descending = [u.username for u in self.read(["-first_name"])]

        self.assertEqual(ascending[-1], "milou")
        self.assertEqual(descending[-1], "milou")
