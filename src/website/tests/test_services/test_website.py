from asgiref.sync import async_to_sync
from django.test import TestCase

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from user.models import User
from website.models import Menu, Page, Website
from website.schemas import WebsiteUpdateSchema
from website.services import WebsiteService
from website.theme import DEFAULT_THEME_ID

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

    # ------------------------------------------
    # Theme and its options
    # ------------------------------------------

    def test_an_unknown_theme_is_refused_and_lists_what_exists(self):
        self.build_website()

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.update(theme="no-such-theme")

        messages = ctx.exception.dict()[self.website_pk()]["theme"]
        self.assertIn("not a known theme", messages[0])
        # The message names the alternatives: the field's own `choices` error
        # could not, which is why this hook exists on top of it.
        self.assertIn(DEFAULT_THEME_ID, messages[0])

    def test_a_null_theme_is_a_field_error(self):
        """`optional_fields = "__all__"` lets `null` through the schema.

        Refused by `ServiceBase.to_internal_values`, which runs
        `Field.validate()` on every supplied value -- so it is keyed by the
        payload's **index**, not by the record's pk, and `validate_data` never
        sees it. That is why the theme hook carries no null guard of its own:
        it would be unreachable.
        """
        self.build_website()

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.update(theme=None)

        self.assertIn("theme", ctx.exception.dict()[0])

    def test_a_known_theme_is_accepted(self):
        self.build_website()

        count, queryset = self.update(theme=DEFAULT_THEME_ID)

        self.assertEqual(count, 1)
        self.assertEqual(queryset.first().theme, DEFAULT_THEME_ID)

    def test_switching_theme_clears_the_stored_options(self):
        self.build_website(theme_options={"nope": 1})

        self.update(theme=DEFAULT_THEME_ID)

        self.assertEqual(Website.objects.get().theme_options, {})

    def test_options_alone_are_validated_against_the_instance_theme(self):
        """The cross-field case no schema can cover.

        Only the options are sent, so the theme to validate them against has to
        come from the stored record.
        """
        self.build_website(theme=DEFAULT_THEME_ID)

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.update(theme_options={"nope": 1})

        self.assertIn("theme_options", ctx.exception.dict()[self.website_pk()])

    def test_theme_and_options_together_validate_against_the_incoming_theme(self):
        self.build_website(theme="stale-theme")

        # The stored theme does not exist, but the payload's does -- so the
        # options are checked against the one being selected.
        count, queryset = self.update(theme=DEFAULT_THEME_ID, theme_options={})

        self.assertEqual(count, 1)
        self.assertEqual(queryset.first().theme, DEFAULT_THEME_ID)

    def test_patching_options_while_the_stored_theme_is_gone_is_refused(self):
        """The read path degrades; a write must not persist options for a dead theme."""
        self.build_website(theme="deleted-from-the-code")

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.update(theme_options={"color_primary": "#fff"})

        self.assertIn("theme", ctx.exception.dict()[self.website_pk()])

    def website_pk(self):
        """The key service errors are filed under on an update.

        `validate_data` runs once per matched record, so its errors are keyed by
        pk -- unlike `to_internal_values`, whose errors are keyed by the
        payload's index.
        """
        return Website.objects.values_list("pk", flat=True).first()
