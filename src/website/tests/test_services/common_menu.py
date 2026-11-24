from website.models import Menu

from website.tests.test_services.common_page import PageServiceCommonMixin

MENU_ROOT_ID = "01M209K5BNS12QRPHXFWVJNVM1"
MENU_FELLOWSHIP_ID = "01M209K5BNS12QRPHXFWVJNVM2"
MENU_JOURNEYS_ID = "01M209K5BNS12QRPHXFWVJNVM3"
MENU_SHIRE_ID = "01M209K5BNS12QRPHXFWVJNVM4"
MENU_MORDOR_ID = "01M209K5BNS12QRPHXFWVJNVM5"
MENU_WEST_ID = "01M209K5BNS12QRPHXFWVJNVM6"

MENU_UNKNOWN_ID = "01M209K5BNS12QRPHXFWVJNVM9"


class MenuServiceCommonMixin(PageServiceCommonMixin):
    """ Two trees, on top of the pages:

        Middle-earth (MENU_ROOT_ID, 20)
         |- The Fellowship (MENU_FELLOWSHIP_ID, 10, link /fellowship/)
         |- Journeys       (MENU_JOURNEYS_ID, 25, link #)
             |- The Shire  (MENU_SHIRE_ID, 10, page The Shire)
             |- Mordor     (MENU_MORDOR_ID, 45, page Mordor)
        The West (MENU_WEST_ID, 30), no item

    Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # One call: `MenuQuerySet.bulk_create` derives each path from the parent
        # instance, so parents only have to come before their children.
        cls.menu_root = Menu(id=MENU_ROOT_ID, name="Middle-earth", sequence=20)
        cls.menu_fellowship = Menu(
            id=MENU_FELLOWSHIP_ID, name="The Fellowship", parent=cls.menu_root, sequence=10, link="/fellowship/"
        )
        cls.menu_journeys = Menu(id=MENU_JOURNEYS_ID, name="Journeys", parent=cls.menu_root, sequence=25, link="#")
        cls.menu_shire = Menu(id=MENU_SHIRE_ID, name="The Shire", parent=cls.menu_journeys, sequence=10, page=cls.page_shire)
        cls.menu_mordor = Menu(id=MENU_MORDOR_ID, name="Mordor", parent=cls.menu_journeys, sequence=45, page=cls.page_mordor)
        cls.menu_west = Menu(id=MENU_WEST_ID, name="The West", sequence=30)
        Menu.objects.bulk_create([
            cls.menu_root, cls.menu_fellowship, cls.menu_journeys, cls.menu_shire, cls.menu_mordor, cls.menu_west,
        ])
