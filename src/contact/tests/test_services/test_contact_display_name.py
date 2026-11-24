from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from contact.services import ContactService
from core.testing import ServiceTestCaseMixin

from contact.tests.test_services.common_contact import (
    CONTACT_ARAGORN_ID,
    CONTACT_PONY_ID,
    CONTACT_UNKNOWN_ID,
    ContactServiceCommonMixin,
)


class ContactDisplayNameServiceTest(ContactServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Contact`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(ContactService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the contacts.
            ("one pk", [CONTACT_PONY_ID], 2, [CONTACT_PONY_ID]),
            ("in the order of the pks", [CONTACT_PONY_ID, CONTACT_ARAGORN_ID], 2, [CONTACT_PONY_ID, CONTACT_ARAGORN_ID]),
            ("a repeated pk appears once", [CONTACT_PONY_ID, CONTACT_PONY_ID], 2, [CONTACT_PONY_ID]),
            ("an unknown pk is absent", [CONTACT_UNKNOWN_ID, CONTACT_PONY_ID], 2, [CONTACT_PONY_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            contacts = async_to_sync(self.service.display_name)(pks, ["id", "display_name", "is_company"])

        self.assertEqual([contact.pk for contact in contacts], expected_pks)
        for contact in contacts:
            self.assertFalse({"display_name", "is_company"} & contact.get_deferred_fields())
            self.assertIn("email", contact.get_deferred_fields())
