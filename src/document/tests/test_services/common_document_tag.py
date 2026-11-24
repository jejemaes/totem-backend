from document.models import DocumentTag

from document.tests.test_services.common_document_tag_category import DocumentTagCategoryServiceCommonMixin

TAG_DRAFT_ID = "01JT0000000000000000000001"
TAG_SIGNED_ID = "01JT0000000000000000000002"
TAG_2026_ID = "01JT0000000000000000000003"

TAG_UNKNOWN_ID = "01JT0000000000000000000099"


class DocumentTagServiceCommonMixin(DocumentTagCategoryServiceCommonMixin):
    """ On top of the categories: Draft (sequence 1) and Signed (2) in Status,
    2026 in Year, none in Kingdom. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tag_draft, cls.tag_signed, cls.tag_2026 = DocumentTag.objects.bulk_create([
            DocumentTag(id=TAG_DRAFT_ID, name="Draft", category=cls.category_status, sequence=1),
            DocumentTag(id=TAG_SIGNED_ID, name="Signed", category=cls.category_status, sequence=2),
            DocumentTag(id=TAG_2026_ID, name="2026", category=cls.category_year),
        ])
