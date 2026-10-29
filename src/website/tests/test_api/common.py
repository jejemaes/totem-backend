from user.tests.test_api.common import CommonTestMixin as UserCommonTestMixin
from website.models import Menu, Page, Website

PAGE_ID1 = "01M209K5BNS12QRPHXFWVJNVP1"
PAGE_ID2 = "01M209K5BNS12QRPHXFWVJNVP2"
PAGE_ID3 = "01M209K5BNS12QRPHXFWVJNVP3"

MENU_ID1 = "01M209K5BNS12QRPHXFWVJNVM1"
MENU_ID2 = "01M209K5BNS12QRPHXFWVJNVM2"
MENU_ID3 = "01M209K5BNS12QRPHXFWVJNVM3"
MENU_ID4 = "01M209K5BNS12QRPHXFWVJNVM4"
MENU_ID5 = "01M209K5BNS12QRPHXFWVJNVM5"

WEBSITE_ID = "01M209K5BNS12QRPHXFWVJNVD1"

PAGE_SCOPES = [
    "totem.websitepage.create",
    "totem.websitepage.read",
    "totem.websitepage.update",
    "totem.websitepage.delete",
]
MENU_SCOPES = [
    "totem.websitemenu.create",
    "totem.websitemenu.read",
    "totem.websitemenu.update",
    "totem.websitemenu.delete",
]
MEDIA_SCOPES = ["totem.websitemedia.create", "totem.websitemedia.read", "totem.websitemedia.delete"]
WEBSITE_SCOPES = ["totem.website.read", "totem.website.update"]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class CommonTestMixin(UserCommonTestMixin):
    """ The site every API test of `website` reads. Data only.

    On top of the users, `role` and API key of `user`:

    Pages:
        PAGE_ID1  "The Shire"  /shire/      published, written by Frodon
        PAGE_ID2  "Mordor"     /mordor/     draft, written by Gollum
        PAGE_ID3  "Rivendell"  /rivendell/  published, no author

    That split of authors is what `website_manage_own_page` is tested against.

    Menus:
        Middle-earth (MENU_ID1, 20)
         |- The Fellowship (MENU_ID2, 10, link /fellowship/)
         |- Journeys       (MENU_ID3, 25, link #)
             |- The Shire  (MENU_ID4, 10, page The Shire)
             |- Mordor     (MENU_ID5, 45, page Mordor)

    Website: the singleton (WEBSITE_ID) "Middle-earth", on that menu, with The
    Shire as homepage.

    No media: a media is a file, and its tests need their own MEDIA_ROOT. `role`
    is granted nothing here: each test class grants the scopes of its resource.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.page_shire, cls.page_mordor, cls.page_rivendell = Page.objects.bulk_create([
            Page(
                id=PAGE_ID1, title="The Shire", slug="shire", content="<p>Hobbiton</p>",
                is_published=True, user=cls.user_frodon,
            ),
            Page(
                id=PAGE_ID2, title="Mordor", slug="mordor", content="<p>Mount Doom</p>",
                user=cls.user_gollum,
            ),
            Page(
                id=PAGE_ID3, title="Rivendell", slug="rivendell", content="<p>The Last Homely House</p>",
                is_published=True,
            ),
        ])

        # One call: `MenuQuerySet.bulk_create` derives each path from the parent
        # instance, so parents only have to come before their children.
        cls.menu_root = Menu(id=MENU_ID1, name="Middle-earth", sequence=20)
        cls.menu_fellowship = Menu(
            id=MENU_ID2, name="The Fellowship", parent=cls.menu_root, sequence=10, link="/fellowship/"
        )
        cls.menu_journeys = Menu(id=MENU_ID3, name="Journeys", parent=cls.menu_root, sequence=25, link="#")
        cls.menu_shire = Menu(
            id=MENU_ID4, name="The Shire", parent=cls.menu_journeys, sequence=10, page=cls.page_shire
        )
        cls.menu_mordor = Menu(
            id=MENU_ID5, name="Mordor", parent=cls.menu_journeys, sequence=45, page=cls.page_mordor
        )
        Menu.objects.bulk_create([
            cls.menu_root, cls.menu_fellowship, cls.menu_journeys, cls.menu_shire, cls.menu_mordor,
        ])

        cls.website = Website.objects.create(
            id=WEBSITE_ID,
            name="Middle-earth",
            headline="Tales of the Third Age",
            meta_authors="The Red Book of Westmarch",
            meta_description="Maps, roads and inns of Middle-earth",
            footer="<p>The Prancing Pony</p>",
            menu=cls.menu_root,
            homepage=cls.page_shire,
        )
