from asgiref.sync import async_to_sync
from django.test import TestCase

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from user.models import User
from website.models import Menu, Page, Website
from website.schemas import WebsiteUpdateSchema
from website.services import WebsiteService

# A well-formed but absent ULID: the schema types a relation with the target's
# primary key type, so a malformed one would be rejected before the service runs.
UNKNOWN_PAGE_ID = "01M209K5BNS12QRPHXFWVJ0000"


class TestWebsiteService(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create(
            username="tintin", email="tintin@moulinsart.com"
        )
        cls.page = Page.objects.create(
            title="Le Hike", slug="hike", content="<p>Mille sabords</p>",
            is_published=True, user=cls.author,
        )
        cls.draft = Page.objects.create(title="Atout Camp", slug="camp")
        cls.menu = Menu.objects.create(name="Main")

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(WebsiteService)

    def build_website(self, **values):
        values.setdefault("name", "Le Trésor")
        values.setdefault("headline", "Rackham le Rouge")
        return Website.objects.create(**values)

    def update(self, **values):
        return async_to_sync(self.service.update)(
            {}, WebsiteUpdateSchema(**values)
        )

    # ------------------------------------------
    # Composition
    # ------------------------------------------

    def test_the_singleton_is_guarded_by_the_absent_mixins(self):
        """The only guard there is, so it needs a contract test.

        Nothing at the database level constrains this table to one row -- see
        `WebsiteService` -- so "you cannot create a second website, and you
        cannot delete the only one" is expressed purely by not composing the two
        mixins. A later refactor adding `CreateMixin` for symmetry would silently
        undo that.
        """
        self.assertFalse(hasattr(WebsiteService, "create"))
        self.assertFalse(hasattr(WebsiteService, "delete"))
        self.assertTrue(hasattr(WebsiteService, "read"))
        self.assertTrue(hasattr(WebsiteService, "update"))

    # ------------------------------------------
    # read_current
    # ------------------------------------------

    def test_read_current_returns_none_on_an_unpopulated_database(self):
        """`/` must answer on a fresh install, so this cannot raise."""
        self.assertIsNone(async_to_sync(self.service.read_current)())

    def test_read_current_returns_the_row(self):
        website = self.build_website()

        self.assertEqual(async_to_sync(self.service.read_current)().pk, website.pk)

    def test_read_current_is_deterministic_with_several_rows(self):
        """Nothing forbids a second row, so the read must not depend on the planner."""
        first = self.build_website(id="01M209K5BNS12QRPHXFWVJNVD1", name="First")
        self.build_website(id="01M209K5BNS12QRPHXFWVJNVD2", name="Second")

        self.assertEqual(async_to_sync(self.service.read_current)().pk, first.pk)

    def test_read_current_is_readable_by_an_anonymous_visitor(self):
        """The public render path, and the reason no `BaseRule` may target `Website`.

        `Environment(None)` is what every request on the public site carries.
        """
        self.build_website()

        self.assertIsNotNone(async_to_sync(self.service.read_current)())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_update_writes_the_identity_and_the_footer(self):
        self.build_website()

        count, queryset = self.update(
            name="Moulinsart",
            headline="Tonnerre de Brest",
            footer="<p>Mille sabords</p>",
            meta_description="Le trésor de Rackham",
        )

        self.assertEqual(count, 1)
        website = queryset.first()
        self.assertEqual(website.name, "Moulinsart")
        self.assertEqual(website.headline, "Tonnerre de Brest")
        self.assertEqual(website.footer, "<p>Mille sabords</p>")
        self.assertEqual(website.meta_description, "Le trésor de Rackham")

    def test_update_sets_the_relations(self):
        self.build_website()

        count, queryset = self.update(menu=self.menu.pk, homepage=self.page.pk)

        self.assertEqual(count, 1)
        website = queryset.first()
        self.assertEqual(website.menu_id, self.menu.pk)
        self.assertEqual(website.homepage_id, self.page.pk)

    def test_the_homepage_may_be_an_unpublished_page(self):
        """Documents the contract, rather than leaving it to be inferred.

        `HomePageView.get_homepage` renders the hero alone when the homepage is
        unpublished or gone, so refusing a draft here would break the natural
        set-then-publish order for no gain.
        """
        self.build_website()

        count, queryset = self.update(homepage=self.draft.pk)

        self.assertEqual(count, 1)
        self.assertEqual(queryset.first().homepage_id, self.draft.pk)

    def test_an_unknown_homepage_is_a_relation_error(self):
        """No `validate_data` needed: relation resolution goes through `PageService.browse`."""
        self.build_website()

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.update(homepage=UNKNOWN_PAGE_ID)

        self.assertIn("homepage", ctx.exception.dict()[0])

    def test_update_on_an_unpopulated_database_writes_nothing(self):
        count, _ = self.update(name="Moulinsart")

        self.assertEqual(count, 0)
