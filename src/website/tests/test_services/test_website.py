from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from website.models import Website
from website.schemas import WebsiteUpdateSchema
from website.services import WebsiteService
from website.theme import DEFAULT_THEME_ID

from website.tests.test_services.common_media import MEDIA_BOOK_ID, MEDIA_MAP_ID
from website.tests.test_services.common_menu import MENU_ROOT_ID, MENU_WEST_ID
from website.tests.test_services.common_page import PAGE_MORDOR_ID, PAGE_SHIRE_ID, PAGE_UNKNOWN_ID
from website.tests.test_services.common_website import WEBSITE_ID, WebsiteServiceCommonMixin

OWN_PAGE = ["website_manage_own_page"]


class WebsiteServiceTest(WebsiteServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `WebsiteService`: the site's own settings, one row. Read and update only.

    No access rules tests on the website itself: `website.security` registers
    no `BaseRule` for `Website`, and the first one would blank the public site,
    which reads the row as `user=None`. Its relations are resolved through their
    own services, whose rules apply: see `test_update_relations_access_rules`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(WebsiteService, user=self.user_frodon)

    # ------------------------------------------
    # Create and Delete
    # ------------------------------------------

    @parameterized.expand([("create",), ("default_values",), ("delete",), ("resequence",)])
    def test_operation_is_not_composed(self, operation):
        # The only guard of the singleton: nothing constrains the table to one
        # row at the database level, so "no second website, and the only one
        # stays" is expressed by not composing the mixins. A refactor adding
        # `CreateMixin` for symmetry would silently undo it.
        self.assertFalse(hasattr(WebsiteService, operation))

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, [WEBSITE_ID]),
            ("by its menu", {"menu": MENU_ROOT_ID}, [WEBSITE_ID]),
            ("nothing matches", {"theme": "furni"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [website.pk for website in async_to_sync(self.service.read)(filters)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "name", "headline"], 2, None),
            # A relation is prefetched, with the fields asked on it.
            ("the homepage", ["id", "homepage__slug"], 3, "shire"),
        ]
    )
    def test_read_fields(self, label, fields, query_count, slug):
        with self.assertNumQueries(query_count):
            websites = list(async_to_sync(self.service.read)(fields=fields))
            loaded = websites[0].homepage.slug if slug else None

        self.assertEqual(loaded, slug)
        self.assertIn("footer", websites[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            (
                "the identity and the footer",
                {},
                {"name": "Arda", "headline": "The Fourth Age", "footer": "<p>Bree</p>", "meta_description": "Maps"},
                5,
                {"name": "Arda", "headline": "The Fourth Age", "footer": "<p>Bree</p>", "meta_description": "Maps"},
            ),
            ("the relations", {}, {"menu": MENU_WEST_ID, "homepage": PAGE_SHIRE_ID}, 7, {"menu_id": MENU_WEST_ID, "homepage_id": PAGE_SHIRE_ID}),
            ("an image as the cover", {}, {"cover_media": MEDIA_MAP_ID}, 6, {"cover_media_id": MEDIA_MAP_ID}),
            # `HomePageView` renders the hero alone when the homepage is a draft:
            # refusing one here would break the natural set-then-publish order.
            ("a draft as the homepage", {}, {"homepage": PAGE_MORDOR_ID}, 6, {"homepage_id": PAGE_MORDOR_ID}),
            ("the relations emptied", {}, {"menu": None, "homepage": None}, 5, {"menu_id": None, "homepage_id": None}),
            # A switch clears the stored options: they are keyed by the names of
            # one theme's options (`WebsiteQuerySet.update`).
            ("a theme switch", {"theme_options": {"color_primary": "#fff"}}, {"theme": "furni"}, 5, {"theme": "furni", "theme_options": {}}),
            # Options sent with the switch still win.
            ("a theme with its options", {}, {"theme": "furni", "theme_options": {"color_primary": "#000"}}, 5, {"theme_options": {"color_primary": "#000"}}),
            # Validated against the incoming theme, not the stored one, gone.
            ("away from a theme gone", {"theme": "deleted-from-the-code"}, {"theme": DEFAULT_THEME_ID, "theme_options": {}}, 5, {"theme": DEFAULT_THEME_ID}),
            # Options alone: validated against the stored theme.
            ("the options alone", {}, {"theme_options": {"color_primary": "#fff"}}, 5, {"theme": DEFAULT_THEME_ID, "theme_options": {"color_primary": "#fff"}}),
        ]
    )
    def test_update(self, label, stored, payload, query_count, expected_values):
        Website.objects.filter(pk=WEBSITE_ID).update(**stored)

        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({}, WebsiteUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([website.pk for website in queryset], [WEBSITE_ID])
        website = Website.objects.get(pk=WEBSITE_ID)
        self.assertEqual({name: getattr(website, name) for name in expected_values}, expected_values)

    def test_update_partial(self):
        async_to_sync(self.service.update)({}, WebsiteUpdateSchema(headline="There and Back Again"))

        website = Website.objects.get(pk=WEBSITE_ID)
        self.assertEqual(
            (website.name, website.headline, website.menu_id, website.homepage_id, website.footer),
            ("Middle-earth", "There and Back Again", MENU_ROOT_ID, PAGE_SHIRE_ID, "<p>The Prancing Pony</p>"),
        )

    @parameterized.expand(
        [
            # `validate_data`, once per matched record: keyed by its pk. It would
            # land in an `<img src>`: a broken image, not a degraded one.
            ("a document as the cover", {}, WebsiteUpdateSchema(cover_media=MEDIA_BOOK_ID), 6, WEBSITE_ID, "cover_media", "must be an image"),
            # The message names the alternatives, which the field's own `choices`
            # error could not: why the hook exists.
            ("an unknown theme", {}, WebsiteUpdateSchema(theme="isengard"), 5, WEBSITE_ID, "theme", DEFAULT_THEME_ID),
            ("options of another theme", {}, WebsiteUpdateSchema(theme_options={"mithril": 1}), 5, WEBSITE_ID, "theme_options", "mithril"),
            # The read path degrades; a write must not persist options for a theme
            # that no longer exists.
            (
                "options while the stored theme is gone",
                {"theme": "deleted-from-the-code"},
                WebsiteUpdateSchema(theme_options={"color_primary": "#fff"}),
                5, WEBSITE_ID, "theme", "no longer exists",
            ),
            # Resolved before any row is read: keyed by the index of the payload.
            ("an unknown homepage", {}, WebsiteUpdateSchema(homepage=PAGE_UNKNOWN_ID), 2, 0, "homepage", ""),
            # Built unvalidated, as another caller than the API could: refused by
            # `to_internal_values`, keyed by the index, and `validate_data` never
            # sees it -- why the theme hook carries no null guard of its own.
            ("a null theme", {}, WebsiteUpdateSchema.model_construct(theme=None), 0, 0, "theme", ""),
        ]
    )
    def test_update_invalid(self, label, stored, data, query_count, error_owner, error_key, message):
        Website.objects.filter(pk=WEBSITE_ID).update(**stored)
        before = Website.objects.get(pk=WEBSITE_ID)

        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({}, data)

        errors = ctx.exception.dict()
        self.assertEqual({key: list(value) for key, value in errors.items()}, {error_owner: [error_key]})
        self.assertIn(message, errors[error_owner][error_key][0])
        website = Website.objects.get(pk=WEBSITE_ID)
        self.assertEqual(
            (website.theme, website.theme_options, website.cover_media_id, website.homepage_id),
            (before.theme, before.theme_options, before.cover_media_id, before.homepage_id),
        )

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({}, {"name": "Arda"})

        self.assertEqual(Website.objects.get(pk=WEBSITE_ID).name, "Middle-earth")

    # No `test_update_batch`: one row.

    def test_update_not_found(self):
        # An unpopulated database: nothing to write, and no error.
        Website.objects.all().delete()

        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({}, WebsiteUpdateSchema(name="Arda"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(Website.objects.exists())

    @parameterized.expand(
        [
            ("no rule", [], PAGE_MORDOR_ID, True),
            # An author holding only their own pages can set the homepage to one
            # of them, and to nothing else: another author's reads as unknown.
            ("own pages, another author's", OWN_PAGE, PAGE_MORDOR_ID, False),
            ("own pages, one's own", OWN_PAGE, PAGE_SHIRE_ID, True),
            ("anonymous: no role, no rule", None, PAGE_MORDOR_ID, True),
        ]
    )
    def test_update_relations_access_rules(self, label, rules, page_id, reached):
        Website.objects.filter(pk=WEBSITE_ID).update(homepage=None)
        if rules is None:
            service = self.get_service(WebsiteService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(WebsiteService, user=self.user_frodon)

        if reached:
            async_to_sync(service.update)({}, WebsiteUpdateSchema(homepage=page_id))
        else:
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(service.update)({}, WebsiteUpdateSchema(homepage=page_id))
            self.assertEqual(list(ctx.exception.dict()[0]), ["homepage"])

        self.assertEqual(Website.objects.get(pk=WEBSITE_ID).homepage_id, page_id if reached else None)
