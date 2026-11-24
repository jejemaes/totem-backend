from website.models import Website
from website.theme import DEFAULT_THEME_ID

from website.tests.test_services.common_media import MediaServiceCommonMixin
from website.tests.test_services.common_menu import MenuServiceCommonMixin

WEBSITE_ID = "01M209K5BNS12QRPHXFWVJNVD1"


class WebsiteServiceCommonMixin(MenuServiceCommonMixin, MediaServiceCommonMixin):
    """ The singleton, on top of the pages, menus and media: "Middle-earth", on
    the Middle-earth menu, with The Shire as homepage and the default theme.
    Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.website = Website.objects.create(
            id=WEBSITE_ID,
            name="Middle-earth",
            headline="Tales of the Third Age",
            meta_authors="The Red Book of Westmarch",
            meta_description="Maps, roads and inns of Middle-earth",
            footer="<p>The Prancing Pony</p>",
            menu=cls.menu_root,
            homepage=cls.page_shire,
            theme=DEFAULT_THEME_ID,
        )
