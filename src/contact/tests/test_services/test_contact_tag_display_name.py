from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from contact.services import ContactTagService
from core.testing import ServiceTestCaseMixin

from contact.tests.test_services.common_contact_tag import (
    TAG_FELLOWSHIP_ID,
    TAG_HOBBIT_ID,
    TAG_UNKNOWN_ID,
    ContactTagServiceCommonMixin,
)


class ContactTagDisplayNameServiceTest(ContactTagServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `ContactTag`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(ContactTagService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the tags.
            ("one pk", [TAG_HOBBIT_ID], 2, [TAG_HOBBIT_ID]),
            ("in the order of the pks", [TAG_HOBBIT_ID, TAG_FELLOWSHIP_ID], 2, [TAG_HOBBIT_ID, TAG_FELLOWSHIP_ID]),
            ("a repeated pk appears once", [TAG_HOBBIT_ID, TAG_HOBBIT_ID], 2, [TAG_HOBBIT_ID]),
            ("an unknown pk is absent", [TAG_UNKNOWN_ID, TAG_HOBBIT_ID], 2, [TAG_HOBBIT_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            tags = async_to_sync(self.service.display_name)(pks, ["id", "name", "color"])

        self.assertEqual([tag.pk for tag in tags], expected_pks)
        for tag in tags:
            self.assertFalse({"name", "color"} & tag.get_deferred_fields())
