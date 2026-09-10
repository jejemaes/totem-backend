from asgiref.sync import async_to_sync
from parameterized import parameterized
from django.db.models import ProtectedError
from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from user.models import User
from website.models import Menu, Page
from website.schemas import PageCreateSchema, PageFilterSchema, PageUpdateSchema
from website.services import PageService
from website.theme import LAYOUT_DEFAULT

# A well-formed but absent v4 UUID: the schema types a relation with the target's
# primary key type, so a malformed one would be rejected before the service runs.
UNKNOWN_USER_ID = "14041cce-4b1a-4c6d-8f3e-000000000000"


class TestPageService(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create(
            username="tintin", email="tintin@moulinsart.com"
        )

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(PageService)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_stamps_the_publication_date_when_published(self):
        # Regression guard: the service inserts through `bulk_create`, which
        # never calls `save()` -- where the stamping used to live.
        pages = async_to_sync(self.service.create)([
            PageCreateSchema(
                title="Le Trésor de Rackham", slug="tresor",
                content="<p>Mille sabords</p>", is_published=True,
            )
        ])

        self.assertEqual(len(pages), 1)
        self.assertIsNotNone(Page.objects.get(pk=pages[0].pk).date_published)

    def test_create_leaves_the_publication_date_unset_when_not_published(self):
        pages = async_to_sync(self.service.create)([
            PageCreateSchema(title="Brouillon", slug="brouillon", content="<p>x</p>")
        ])

        self.assertIsNone(Page.objects.get(pk=pages[0].pk).date_published)

    def test_create_fills_the_update_date(self):
        # Documents that `auto_now` *does* run through `bulk_create`, which calls
        # `pre_save` on every field. Only `queryset.update()` needs compensating.
        pages = async_to_sync(self.service.create)([
            PageCreateSchema(title="Page", slug="page", content="<p>x</p>")
        ])

        self.assertIsNotNone(Page.objects.get(pk=pages[0].pk).update_date)

    def test_create_resolves_the_author_through_its_service(self):
        pages = async_to_sync(self.service.create)([
            PageCreateSchema(
                title="Page", slug="page", content="<p>x</p>", user=str(self.author.pk)
            )
        ])

        self.assertEqual(Page.objects.get(pk=pages[0].pk).user_id, self.author.pk)

    def test_create_with_an_unknown_author_is_rejected(self):
        # Relations are not checked by the schema, which only types the primary
        # key: the service resolves them through the related service, so access
        # rules apply to what a payload may point at.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([
                PageCreateSchema(
                    title="Page", slug="page", content="<p>x</p>",
                    user=UNKNOWN_USER_ID,
                )
            ])

        self.assertIn("user", ctx.exception.dict()[0])
        self.assertFalse(Page.objects.exists())

    def test_create_with_a_duplicate_slug_is_rejected(self):
        Page.objects.create(title="First", slug="dup", content="<p>x</p>")

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.create)([
                PageCreateSchema(title="Second", slug="dup", content="<p>x</p>")
            ])

        # The message comes from the constraint's `violation_error_message`. Left
        # unset, django's default is used and leaks a raw `%(name)s`.
        self.assertIn(
            "A document with that slug already exists.",
            str(ctx.exception.dict()["__all__"]),
        )

    def test_the_slug_is_validated_by_the_schema(self):
        with self.assertRaises(PydanticValidationError):
            PageCreateSchema(title="Page", slug="not a slug", content="<p>x</p>")

    def test_the_html_content_is_validated_by_the_schema(self):
        with self.assertRaises(PydanticValidationError):
            PageCreateSchema(
                title="Page", slug="page", content="<script>alert(1)</script>"
            )

    # ------------------------------------------
    # Tests Widget Markers
    # ------------------------------------------

    def test_a_widget_marker_is_accepted_in_the_content(self):
        # `Page.content` opts in with `allow_widget`, so the marker survives all
        # the way to the database.
        content = '<div><t-widget name="last-page" attrs=\'{"limit":5}\'/></div>'

        pages = async_to_sync(self.service.create)([
            PageCreateSchema(title="Page", slug="page", content=content)
        ])

        self.assertEqual(Page.objects.get(pk=pages[0].pk).content, content)

    @parameterized.expand(
        [
            ("attrs is not json", '<div><t-widget name="x" attrs="nope"/></div>'),
            ("name is absent", "<div><t-widget/></div>"),
            (
                "marker inside a marker",
                '<div><t-widget name="a"><t-widget name="b"/></t-widget></div>',
            ),
        ]
    )
    def test_a_malformed_widget_marker_is_refused(self, dummy, content):
        # The structural consequence of inline parameters: they are validated
        # when the *page* is saved, not when a widget row is. The field
        # validator becomes a pydantic validator on the schema, through
        # `convert_validators`, so the service path is covered too.
        with self.assertRaises(PydanticValidationError):
            PageCreateSchema(title="Page", slug="page", content=content)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_update_moves_the_update_date(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")
        before = page.update_date

        async_to_sync(self.service.update)(
            {"id": page.pk}, PageUpdateSchema(title="Renamed")
        )

        page.refresh_from_db()
        self.assertEqual(page.title, "Renamed")
        # Regression guard: the service updates through `queryset.update()`,
        # which bypasses the `auto_now` of the field.
        self.assertGreater(page.update_date, before)

    def test_update_stamps_the_publication_date_when_publishing(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")
        self.assertIsNone(page.date_published)

        async_to_sync(self.service.update)(
            {"id": page.pk}, PageUpdateSchema(is_published=True)
        )

        page.refresh_from_db()
        self.assertIsNotNone(page.date_published)

    def test_update_of_another_field_leaves_the_publication_date(self):
        page = Page.objects.create(
            title="Page", slug="page", content="<p>x</p>", is_published=True
        )
        page.refresh_from_db()
        published_at = page.date_published

        async_to_sync(self.service.update)(
            {"id": page.pk}, PageUpdateSchema(title="Renamed")
        )

        page.refresh_from_db()
        self.assertEqual(page.date_published, published_at)

    def test_the_derived_dates_are_not_writable(self):
        for schema in (PageCreateSchema, PageUpdateSchema):
            self.assertNotIn("date_published", schema.model_fields)
            self.assertNotIn("update_date", schema.model_fields)

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    def test_read_filters_on_the_publication_state(self):
        Page.objects.create(
            title="Published", slug="pub", content="<p>x</p>", is_published=True
        )
        Page.objects.create(title="Draft", slug="draft", content="<p>x</p>")

        queryset = async_to_sync(self.service.read)(
            PageFilterSchema(is_published=True)
        )

        self.assertEqual([p.title for p in queryset], ["Published"])

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")

        async_to_sync(self.service.delete)({"id": page.pk})

        self.assertFalse(Page.objects.filter(pk=page.pk).exists())

    def test_delete_is_refused_while_a_menu_item_targets_the_page(self):
        page = Page.objects.create(title="Page", slug="page", content="<p>x</p>")
        root = Menu.objects.create(name="Root")
        Menu.objects.create(name="Item", parent=root, page=page)

        # `Menu.page` is `PROTECT`. `_delete_atomic` maps the `ProtectedError` the
        # collector raises through `_database_error_to_validation_error`, like every
        # other failed write, so no raw django exception reaches a controller.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.delete)({"id": page.pk})

        self.assertEqual(ctx.exception.code, "protected_error")
        # The message names the relation that protects the page, not just the fact.
        self.assertIn("Menu.page", str(ctx.exception.dict()["__all__"]))
        self.assertTrue(Page.objects.filter(pk=page.pk).exists())

    # ------------------------------------------
    # Layout
    # ------------------------------------------

    def test_an_unknown_layout_never_reaches_the_service(self):
        """`choices` is why `PageService` needs no hook for this.

        `core.schemas.fields` builds a pydantic `Enum` from the field's choices,
        so the schema refuses an unknown id with a message that already names
        every valid one -- better than anything a service hook would write. A
        caller passing a dict instead of a schema is covered too:
        `to_internal_values` runs `Field.validate()`, which enforces `choices`.
        """
        with self.assertRaises(PydanticValidationError) as ctx:
            PageCreateSchema(
                title="Le Hike",
                slug="hike",
                content="<p>x</p>",
                layout="no-such-layout",
            )

        self.assertIn(LAYOUT_DEFAULT, str(ctx.exception))

    def test_an_unknown_layout_in_a_raw_dict_is_refused_too(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.to_internal_values)(
                [{"layout": "no-such-layout"}]
            )

        self.assertIn("layout", ctx.exception.dict()[0])

    def test_a_layout_the_active_theme_does_not_implement_is_still_valid(self):
        """The asymmetry the whole feature rests on.

        The vocabulary is closed; theme coverage is open and resolved with a
        fallback when the page renders. So a page may carry a layout no
        installed theme implements, and must stay valid -- otherwise switching
        theme could invalidate existing pages, which is precisely what the
        three-rung lookup exists to prevent.
        """
        pages = async_to_sync(self.service.create)([
            PageCreateSchema(
                title="Le Hike", slug="hike", content="<p>x</p>", layout="sidebar-right"
            )
        ])

        self.assertEqual(pages[0].layout, "sidebar-right")

    def test_a_null_layout_is_a_field_error(self):
        """Caught by `to_internal_values`, so keyed by index rather than by pk."""
        page = Page.objects.create(title="Le Hike", slug="hike", content="<p>x</p>")

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": page.pk}, PageUpdateSchema(layout=None)
            )

        self.assertIn("layout", ctx.exception.dict()[0])
