from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from document.services import DocumentTagCategoryService

from document.tests.test_services.common_document_tag_category import CATEGORY_STATUS_ID, CATEGORY_YEAR_ID, CATEGORY_UNKNOWN_ID, DocumentTagCategoryServiceCommonMixin


class DocumentTagCategoryDisplayNameServiceTest(DocumentTagCategoryServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `DocumentTagCategory`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentTagCategoryService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the records.
            ("one pk", [CATEGORY_YEAR_ID], 2, [CATEGORY_YEAR_ID]),
            ("in the order of the pks", [CATEGORY_YEAR_ID, CATEGORY_STATUS_ID], 2, [CATEGORY_YEAR_ID, CATEGORY_STATUS_ID]),
            ("a repeated pk appears once", [CATEGORY_YEAR_ID, CATEGORY_YEAR_ID], 2, [CATEGORY_YEAR_ID]),
            ("an unknown pk is absent", [CATEGORY_UNKNOWN_ID, CATEGORY_YEAR_ID], 2, [CATEGORY_YEAR_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            records = async_to_sync(self.service.display_name)(pks, ["id", "name", "color"])

        self.assertEqual([record.pk for record in records], expected_pks)
        for record in records:
            self.assertFalse({"name", "color"} & record.get_deferred_fields())
            self.assertIn("sequence", record.get_deferred_fields())
