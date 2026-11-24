from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from document.services import DocumentService

from document.tests.test_services.common_document import (
    DOCUMENT_MINUTES_ID,
    DOCUMENT_NOTES_ID,
    DOCUMENT_UNKNOWN_ID,
    DocumentServiceCommonMixin,
)


class DocumentDisplayNameServiceTest(DocumentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Document`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the documents.
            ("one pk", [DOCUMENT_MINUTES_ID], 2, [DOCUMENT_MINUTES_ID]),
            ("in the order of the pks", [DOCUMENT_MINUTES_ID, DOCUMENT_NOTES_ID], 2, [DOCUMENT_MINUTES_ID, DOCUMENT_NOTES_ID]),
            ("a repeated pk appears once", [DOCUMENT_MINUTES_ID, DOCUMENT_MINUTES_ID], 2, [DOCUMENT_MINUTES_ID]),
            ("an unknown pk is absent", [DOCUMENT_UNKNOWN_ID, DOCUMENT_MINUTES_ID], 2, [DOCUMENT_MINUTES_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            documents = async_to_sync(self.service.display_name)(pks, ["id", "name"])

        self.assertEqual([document.pk for document in documents], expected_pks)
        for document in documents:
            self.assertNotIn("name", document.get_deferred_fields())
            self.assertIn("text_content", document.get_deferred_fields())
