from document.models import DocumentTagCategory
from user.tests.test_services.common_user import UserServiceCommonMixin

CATEGORY_STATUS_ID = "01JD0000000000000000000001"
CATEGORY_YEAR_ID = "01JD0000000000000000000002"
CATEGORY_KINGDOM_ID = "01JD0000000000000000000003"

CATEGORY_UNKNOWN_ID = "01JD0000000000000000000099"


class DocumentTagCategoryServiceCommonMixin(UserServiceCommonMixin):
    """ Three tag categories, on top of the users of `user`: Status (sequence 1,
    color 3), Year (2) and Kingdom (3). Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.category_status, cls.category_year, cls.category_kingdom = DocumentTagCategory.objects.bulk_create([
            DocumentTagCategory(id=CATEGORY_STATUS_ID, name="Status", sequence=1, color=3),
            DocumentTagCategory(id=CATEGORY_YEAR_ID, name="Year", sequence=2),
            DocumentTagCategory(id=CATEGORY_KINGDOM_ID, name="Kingdom", sequence=3),
        ])
