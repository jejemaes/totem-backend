from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from document.models import DocumentTagCategory
from document.services import DocumentTagCategoryService

from document.tests.test_services.common_document_tag_category import (
    CATEGORY_KINGDOM_ID,
    CATEGORY_STATUS_ID,
    CATEGORY_UNKNOWN_ID,
    CATEGORY_YEAR_ID,
    DocumentTagCategoryServiceCommonMixin,
)

# As the common data leaves them.
SEQUENCES = {CATEGORY_STATUS_ID: 1, CATEGORY_YEAR_ID: 2, CATEGORY_KINGDOM_ID: 3}


class DocumentTagCategoryResequenceServiceTest(DocumentTagCategoryServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `DocumentTagCategory`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentTagCategoryService, user=self.user_frodon)

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the transaction, the rows found, then one UPDATE whatever
            # their number.
            ("every category", [CATEGORY_YEAR_ID, CATEGORY_KINGDOM_ID, CATEGORY_STATUS_ID], 0, 5, {CATEGORY_YEAR_ID: 1, CATEGORY_KINGDOM_ID: 2, CATEGORY_STATUS_ID: 3}),
            # Only the records given are numbered.
            ("a partial list", [CATEGORY_KINGDOM_ID], 0, 5, {CATEGORY_KINGDOM_ID: 1}),
            ("with an offset", [CATEGORY_KINGDOM_ID, CATEGORY_YEAR_ID], 10, 5, {CATEGORY_KINGDOM_ID: 11, CATEGORY_YEAR_ID: 12}),
            ("no pk", [], 0, 0, {}),
        ]
    )
    def test_resequence(self, label, pks, offset, query_count, expected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.resequence)(pks, offset=offset)

        self.assertEqual(count, len(pks))
        self.assertEqual(dict(DocumentTagCategory.objects.values_list("pk", "sequence")), {**SEQUENCES, **expected})

    @parameterized.expand(
        [
            # All or nothing, and none of these told apart: keyed on `ids`.
            # Refused before any query.
            ("a repeated pk", [CATEGORY_YEAR_ID, CATEGORY_YEAR_ID], 0),
            ("an unknown pk", [CATEGORY_YEAR_ID, CATEGORY_UNKNOWN_ID], 5),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk", [CATEGORY_YEAR_ID, "not-a-ulid"], 5),
        ]
    )
    def test_resequence_invalid(self, label, pks, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.resequence)(pks)

        self.assertEqual(list(ctx.exception.dict()), ["ids"])
        self.assertEqual(dict(DocumentTagCategory.objects.values_list("pk", "sequence")), SEQUENCES)
