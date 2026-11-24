from website.models import Page
from user.tests.test_services.common_user import UserServiceCommonMixin

PAGE_SHIRE_ID = "01M209K5BNS12QRPHXFWVJNVP1"
PAGE_MORDOR_ID = "01M209K5BNS12QRPHXFWVJNVP2"
PAGE_RIVENDELL_ID = "01M209K5BNS12QRPHXFWVJNVP3"

# Well-formed but absent.
PAGE_UNKNOWN_ID = "01M209K5BNS12QRPHXFWVJNVP9"


class PageServiceCommonMixin(UserServiceCommonMixin):
    """ Three pages, on top of the users and roles of `user`:

        The Shire  /shire/      published, written by Frodon -- the acting user
        Mordor     /mordor/     draft, written by Gollum
        Rivendell  /rivendell/  published, no author

    That split of authors is what `website_manage_own_page` is tested against.
    Bulk created, so `date_published` is stamped by `PageQuerySet.bulk_create`.
    Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.page_shire, cls.page_mordor, cls.page_rivendell = Page.objects.bulk_create([
            Page(
                id=PAGE_SHIRE_ID, title="The Shire", slug="shire", content="<p>Hobbiton</p>",
                is_published=True, user=cls.user_frodon,
            ),
            Page(id=PAGE_MORDOR_ID, title="Mordor", slug="mordor", content="<p>Mount Doom</p>", user=cls.user_gollum),
            Page(
                id=PAGE_RIVENDELL_ID, title="Rivendell", slug="rivendell",
                content="<p>The Last Homely House</p>", is_published=True,
            ),
        ])
