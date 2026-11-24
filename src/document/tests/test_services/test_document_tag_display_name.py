from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from document.services import DocumentTagService

from document.tests.test_services.common_document_tag import TAG_DRAFT_ID, TAG_SIGNED_ID, TAG_UNKNOWN_ID, DocumentTagServiceCommonMixin


class DocumentTagDisplayNameServiceTest(DocumentTagServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `DocumentTag`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentTagService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the records.
            ("one pk", [TAG_SIGNED_ID], 2, [TAG_SIGNED_ID]),
            ("in the order of the pks", [TAG_SIGNED_ID, TAG_DRAFT_ID], 2, [TAG_SIGNED_ID, TAG_DRAFT_ID]),
            ("a repeated pk appears once", [TAG_SIGNED_ID, TAG_SIGNED_ID], 2, [TAG_SIGNED_ID]),
            ("an unknown pk is absent", [TAG_UNKNOWN_ID, TAG_SIGNED_ID], 2, [TAG_SIGNED_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            records = async_to_sync(self.service.display_name)(pks, ["id", "name"])

        self.assertEqual([record.pk for record in records], expected_pks)
        for record in records:
            self.assertFalse({"name"} & record.get_deferred_fields())
            self.assertIn("sequence", record.get_deferred_fields())
