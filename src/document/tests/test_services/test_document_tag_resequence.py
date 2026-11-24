from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from document.models import DocumentTag
from document.services import DocumentTagService

from document.tests.test_services.common_document_tag import (
    TAG_2026_ID,
    TAG_DRAFT_ID,
    TAG_SIGNED_ID,
    TAG_UNKNOWN_ID,
    DocumentTagServiceCommonMixin,
)
from document.tests.test_services.common_document_tag_category import CATEGORY_STATUS_ID

# As the common data leaves them.
SEQUENCES = {TAG_DRAFT_ID: 1, TAG_SIGNED_ID: 2, TAG_2026_ID: 10}


class DocumentTagResequenceServiceTest(DocumentTagServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `DocumentTag`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentTagService, user=self.user_frodon)

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the transaction, the rows found, then one UPDATE whatever
            # their number.
            ("within a category", [TAG_SIGNED_ID, TAG_DRAFT_ID], None, 0, 5, {TAG_SIGNED_ID: 1, TAG_DRAFT_ID: 2}),
            # As the nested route of a category does.
            ("within the filters", [TAG_SIGNED_ID, TAG_DRAFT_ID], {"category_id": CATEGORY_STATUS_ID}, 0, 5, {TAG_SIGNED_ID: 1, TAG_DRAFT_ID: 2}),
            ("with an offset", [TAG_2026_ID], None, 4, 5, {TAG_2026_ID: 5}),
            ("no pk", [], None, 0, 0, {}),
        ]
    )
    def test_resequence(self, label, pks, filters, offset, query_count, expected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.resequence)(pks, filters=filters, offset=offset)

        self.assertEqual(count, len(pks))
        self.assertEqual(dict(DocumentTag.objects.values_list("pk", "sequence")), {**SEQUENCES, **expected})

    @parameterized.expand(
        [
            # All or nothing, and none of these told apart: keyed on `ids`.
            # Refused before any query.
            ("a repeated pk", [TAG_DRAFT_ID, TAG_DRAFT_ID], None, 0),
            ("an unknown pk", [TAG_DRAFT_ID, TAG_UNKNOWN_ID], None, 5),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk", [TAG_DRAFT_ID, "not-a-ulid"], None, 5),
            ("outside the filters", [TAG_DRAFT_ID, TAG_2026_ID], {"category_id": CATEGORY_STATUS_ID}, 5),
        ]
    )
    def test_resequence_invalid(self, label, pks, filters, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.resequence)(pks, filters=filters)

        self.assertEqual(list(ctx.exception.dict()), ["ids"])
        self.assertEqual(dict(DocumentTag.objects.values_list("pk", "sequence")), SEQUENCES)
