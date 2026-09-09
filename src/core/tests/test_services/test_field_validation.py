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
        """The live gap, and the reason this is not merely defensive.

        `optional_fields = "__all__"` types every update field `Optional`, so
        `null` passes the schema and reaches the service. Without this check it
        only fails as an integrity error from the database -- unkeyed, and
        unattributable to a field by any client.
        """
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": self.actor.pk}, UserUpdateSchema(language=None)
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
