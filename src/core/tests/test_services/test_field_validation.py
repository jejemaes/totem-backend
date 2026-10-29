"""Model-level field rules on the service write paths.

`Field.run_validators()` only runs what a field declares in `validators=[...]`.
The rules django keeps in `Field.validate()` -- `choices`, `null`, `blank` --
are reached exclusively through `Model.full_clean()`, which no service write
path calls: `CreateMixin` goes to `bulk_create` and `UpdateMixin` to
`queryset.update()`. `ServiceBase.to_internal_values` closes that gap for every
value a caller actually sends, on both paths at once.
"""

from asgiref.sync import async_to_sync
from django.test import TestCase

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from account.services import BudgetLineService
from user.models import User
from user.schemas import UserUpdateSchema
from user.services import UserService


class TestFieldValidationOnWrite(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create(
            username="tintin", email="tintin@moulinsart.com"
        )

    @property
    def service(self):
        return Environment(user=self.actor).get(UserService)

    def internal_values(self, values):
        return async_to_sync(self.service.to_internal_values)([values])

    # -----------------------------------------------------------------
    # choices
    # -----------------------------------------------------------------

    def test_a_value_outside_choices_is_refused(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.internal_values({"language": "kl"})

        self.assertIn("language", ctx.exception.dict()[0])

    def test_a_value_inside_choices_passes(self):
        self.assertEqual(self.internal_values({"language": "fr"}), [{"language": "fr"}])

    # -----------------------------------------------------------------
    # null
    # -----------------------------------------------------------------

    def test_null_into_a_not_null_column_is_a_field_error(self):
        """The guard for every caller the schema does not stand in front of.

        Through the API, the update schema refuses `null` on a NOT NULL column
        itself: `optional_fields = "__all__"` makes a field omittable, not
        nullable. A schema built without validation -- as here -- or any other
        caller of the service still reaches this check, and without it the
        `null` would only fail as an integrity error from the database: unkeyed,
        and unattributable to a field.
        """
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": self.actor.pk}, UserUpdateSchema.model_construct(language=None)
            )

        # Keyed by the payload's index and not by the record's pk: this runs in
        # `to_internal_values`, before `update()` has matched a single row. The
        # pk-keyed errors are the ones `validate_data` raises later.
        self.assertIn("language", ctx.exception.dict()[0])
        self.actor.refresh_from_db()
        self.assertEqual(self.actor.language, "fr")

    # -----------------------------------------------------------------
    # relations are deliberately left alone
    # -----------------------------------------------------------------

    def test_a_relation_is_not_checked_here(self):
        """`ForeignKey.validate()` must never run on this path.

        It looks the related row up through `_base_manager`, which no access rule
        narrows: it would answer "exists" for a record the acting user cannot
        see, and so contradict the scoped resolution that reports
        `RelationNotFound` a few lines below. An unknown relation must still come
        back as a relation error, never as a field-validity one.
        """
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.internal_values({"roles": ["01M209K5BNS12QRPHXFWVJNVD1"]})

        self.assertIn("roles", ctx.exception.dict()[0])

    def test_null_into_a_not_null_relation_is_a_field_error(self):
        """The null check of `Field.validate()` is kept for relations, without
        its lookup: unkeyed, a `null` position reached the database as an
        integrity error naming no field."""
        service = Environment(user=self.actor).get(BudgetLineService)

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(service.to_internal_values)([{"position": None}])

        self.assertIn("position", ctx.exception.dict()[0])

    def test_none_on_a_many_to_many_is_not_a_null_error(self):
        # A many-to-many has no column: a creation hands it `None` for "not
        # given", and that must not read as a null into a NOT NULL field. It
        # resolves to no record.
        self.assertEqual(self.internal_values({"roles": None}), [{"roles": []}])
