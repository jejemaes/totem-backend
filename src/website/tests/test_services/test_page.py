from uuid import UUID

from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from user.tests.test_services.common_user import USER_FRODON_ID, USER_GOLLUM_ID, USER_SAM_ID
from website.models import Page
from website.schemas import PageCreateSchema, PageFilterSchema, PageUpdateSchema
from website.services import PageService
from website.theme import LAYOUT_DEFAULT

from website.tests.test_services.common_menu import MenuServiceCommonMixin
from website.tests.test_services.common_page import (
    PAGE_MORDOR_ID,
    PAGE_RIVENDELL_ID,
    PAGE_SHIRE_ID,
    PAGE_UNKNOWN_ID,
)

ALL_PAGE_IDS = [PAGE_SHIRE_ID, PAGE_MORDOR_ID, PAGE_RIVENDELL_ID]

USER_UNKNOWN_ID = "5263de93-e694-41ef-b873-34610551afcd"

OWN = ["website_manage_own_page"]

SLUG_TAKEN = "A document with that slug already exists."


class PageServiceTest(MenuServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `PageService`: create, read, update, delete and default values.

    `update_date` and `date_published` are kept by `PageQuerySet`, on the write
    paths that never call `save()`: each write here reads them back.
    """

    payload_create = {"title": "Bree", "slug": "bree", "content": "<p>The Prancing Pony</p>"}

    def setUp(self):
        super().setUp()
        self.service = self.get_service(PageService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the author defaulted to the acting user and resolved as
            # any relation, the transaction, the insert, and the access rules
            # checked on the rows written.
            ("required fields only", {}, 6, {"user_id": UUID(USER_FRODON_ID), "is_published": False, "layout": LAYOUT_DEFAULT}),
            ("another author", {"user": USER_SAM_ID}, 6, {"user_id": UUID(USER_SAM_ID)}),
            # Given, even as null, a field is never overwritten by its default.
            ("no author", {"user": None}, 5, {"user_id": None}),
            # The vocabulary is closed, the coverage of a theme open: a layout no
            # installed theme implements stays valid, or switching theme would
            # invalidate existing pages.
            ("a layout the theme does not implement", {"layout": "sidebar-right"}, 6, {"layout": "sidebar-right"}),
            # `Page.content` opts in with `allow_widget`: the marker survives.
            (
                "a widget marker in the content",
                {"content": '<div><t-widget name="last-page" attrs=\'{"limit":5}\'/></div>'},
                6,
                {"content": '<div><t-widget name="last-page" attrs=\'{"limit":5}\'/></div>'},
            ),
        ]
    )
    def test_create(self, label, values, query_count, expected_values):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([PageCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual([page.slug for page in instances], ["bree"])
        page = Page.objects.get(pk=instances[0].pk)
        self.assertEqual({name: getattr(page, name) for name in expected_values}, expected_values)
        # `auto_now` does run through `bulk_create`, which calls `pre_save`.
        self.assertIsNotNone(page.update_date)

    @parameterized.expand(
        [
            # Stamped by `PageQuerySet.bulk_create`: the service never calls the
            # `save()` where the stamping used to live.
            ("published", True, True),
            ("a draft", False, False),
        ]
    )
    def test_create_publication_date(self, label, is_published, stamped):
        with self.assertNumQueries(6):
            instances = async_to_sync(self.service.create)(
                [PageCreateSchema(**self.payload_create, is_published=is_published)]
            )

        self.assertEqual(Page.objects.get(pk=instances[0].pk).date_published is not None, stamped)

    @parameterized.expand(
        [
            # The message comes from the constraint's `violation_error_message`.
            # Left unset, django's default leaks a raw `%(name)s`.
            ("slug taken", {"slug": "shire"}, 6, SLUG_TAKEN),
        ]
    )
    def test_create_invalid(self, label, values, query_count, message):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([PageCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(Page.objects.count(), 3)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([self.payload_create])

        self.assertEqual(Page.objects.count(), 3)

    @parameterized.expand(
        [
            # Not checked by the schema, which only types the pk: resolved through
            # the user service, so the access rules of the users apply.
            ("unknown author", {"user": USER_UNKNOWN_ID}, 2, "user"),
        ]
    )
    def test_create_relations(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([PageCreateSchema(**{**self.payload_create, **values})])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Page.objects.count(), 3)

    @parameterized.expand(
        [
            ("every input valid", [{}, {"title": "Moria", "slug": "moria"}], 6, None),
            # All or nothing: the valid first input is not written either.
            ("the second input taken", [{}, {"title": "Mordor again", "slug": "mordor"}], 6, "__all__"),
        ]
    )
    def test_create_batch(self, label, values_list, query_count, error_key):
        data = [PageCreateSchema(**{**self.payload_create, **values}) for values in values_list]

        with self.assertNumQueries(query_count):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([page.slug for page in instances], ["bree", "moria"])
            self.assertEqual(Page.objects.count(), 5)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(Page.objects.filter(slug="bree").exists())

    @parameterized.expand(
        [
            ("every field", None, {"user": USER_FRODON_ID, "is_published": False, "layout": LAYOUT_DEFAULT}),
            ("the fields asked", ["user", "layout"], {"user": USER_FRODON_ID, "layout": LAYOUT_DEFAULT}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual(
            {name: str(value) if name == "user" else value for name, value in values.items() if value is not None},
            expected,
        )

    def test_default_values_without_acting_user(self):
        # An API key acts as nobody: there is no author to default to.
        service = self.get_service(PageService)

        with self.assertNumQueries(0):
            values = async_to_sync(service.default_values)(["user", "layout"])

        self.assertEqual((values.get("user"), values["layout"]), (None, LAYOUT_DEFAULT))

    @parameterized.expand(
        [
            ("no rule", [], {"user": USER_GOLLUM_ID}, True),
            # The default author makes it one's own: no need to name oneself.
            ("own pages, the author left out", OWN, {}, True),
            ("own pages, for another author", OWN, {"user": USER_GOLLUM_ID}, False),
            ("own pages, for no author", OWN, {"user": None}, False),
            ("anonymous: no role, no rule", None, {"user": USER_GOLLUM_ID}, True),
        ]
    )
    def test_create_access_rules(self, label, rules, values, created):
        service = self.service_with_rules(rules)
        data = PageCreateSchema(**{**self.payload_create, **values})

        if created:
            async_to_sync(service.create)([data])
        else:
            # Checked on the rows written, inside the transaction: rolled back.
            with self.assertRaises(PermissionDenied):
                async_to_sync(service.create)([data])

        self.assertEqual(Page.objects.filter(slug="bree").exists(), created)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_PAGE_IDS),
            ("a dict", {"slug": "shire"}, [PAGE_SHIRE_ID]),
            # The filter schema of the API, with its own lookups.
            ("published", PageFilterSchema(is_published=True), [PAGE_SHIRE_ID, PAGE_RIVENDELL_ID]),
            ("drafts", PageFilterSchema(is_published=False), [PAGE_MORDOR_ID]),
            ("by author", PageFilterSchema(author=[USER_GOLLUM_ID]), [PAGE_MORDOR_ID]),
            ("by a search term", PageFilterSchema(search="dell"), [PAGE_RIVENDELL_ID]),
            ("by layout", PageFilterSchema(layout=[LAYOUT_DEFAULT]), ALL_PAGE_IDS),
            ("nothing matches", PageFilterSchema(title="Isengard"), []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [page.pk for page in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by title", ["title"], [PAGE_MORDOR_ID, PAGE_RIVENDELL_ID, PAGE_SHIRE_ID]),
            ("by slug, descending", ["-slug"], [PAGE_SHIRE_ID, PAGE_RIVENDELL_ID, PAGE_MORDOR_ID]),
            ("by state, then title", ["is_published", "title"], [PAGE_MORDOR_ID, PAGE_RIVENDELL_ID, PAGE_SHIRE_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [page.pk for page in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "title", "slug"], 2, None),
            # The author is prefetched, with the fields asked on it.
            ("the author", ["id", "user__username"], 3, "frodon@lacomte.com"),
        ]
    )
    def test_read_fields(self, label, fields, query_count, username):
        with self.assertNumQueries(query_count):
            pages = list(async_to_sync(self.service.read)({"id": PAGE_SHIRE_ID}, fields=fields))
            loaded = pages[0].user.username if username else None

        self.assertEqual(loaded, username)
        self.assertIn("content", pages[0].get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], None, ALL_PAGE_IDS),
            ("own pages", OWN, None, [PAGE_SHIRE_ID]),
            ("two roles, combined with OR", OWN, [], [PAGE_SHIRE_ID]),
            ("anonymous: no role, no rule", None, None, ALL_PAGE_IDS),
        ]
    )
    def test_read_access_rules(self, label, rules, second_role_rules, expected_pks):
        service = self.service_with_rules(rules, second_role_rules)

        pks = [page.pk for page in async_to_sync(service.read)()]

        self.assertCountEqual(pks, expected_pks)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the title", {"title": "The Shire, Hobbiton"}, 5, {"title": "The Shire, Hobbiton"}),
            ("the slug", {"slug": "the-shire"}, 5, {"slug": "the-shire"}),
            ("another author", {"user": USER_SAM_ID}, 6, {"user_id": UUID(USER_SAM_ID)}),
            ("no author", {"user": None}, 5, {"user_id": None}),
            ("the layout", {"layout": "sidebar-right"}, 5, {"layout": "sidebar-right"}),
        ]
    )
    def test_update(self, label, payload, query_count, expected_values):
        before = Page.objects.get(pk=PAGE_SHIRE_ID)

        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": PAGE_SHIRE_ID}, PageUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([page.pk for page in queryset], [PAGE_SHIRE_ID])
        page = Page.objects.get(pk=PAGE_SHIRE_ID)
        self.assertEqual({name: getattr(page, name) for name in expected_values}, expected_values)
        # `queryset.update()` bypasses `auto_now`: `PageQuerySet.update` moves it.
        self.assertGreater(page.update_date, before.update_date)
        # Another field than the state leaves the publication date alone.
        self.assertEqual(page.date_published, before.date_published)

    @parameterized.expand(
        [
            ("publishing a draft", PAGE_MORDOR_ID, True),
            # The mere presence of the state restamps, as `save()` does with
            # `update_fields`: unpublishing moves the date too. Pinned as found.
            ("unpublishing", PAGE_SHIRE_ID, False),
            ("publishing again", PAGE_SHIRE_ID, True),
        ]
    )
    def test_update_publication_date(self, label, pk, is_published):
        before = Page.objects.get(pk=pk).date_published

        with self.assertNumQueries(5):
            async_to_sync(self.service.update)({"id": pk}, PageUpdateSchema(is_published=is_published))

        page = Page.objects.get(pk=pk)
        self.assertEqual(page.is_published, is_published)
        self.assertIsNotNone(page.date_published)
        self.assertNotEqual(page.date_published, before)

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": PAGE_MORDOR_ID}, PageUpdateSchema(title="Mordor, Barad-dûr"))

        page = Page.objects.get(pk=PAGE_MORDOR_ID)
        self.assertEqual(
            (page.title, page.slug, page.content, page.is_published, page.user_id),
            ("Mordor, Barad-dûr", "mordor", "<p>Mount Doom</p>", False, UUID(USER_GOLLUM_ID)),
        )

    @parameterized.expand(
        [
            ("slug taken", PageUpdateSchema(slug="mordor"), 6, {"__all__": ["__all__"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown author", PageUpdateSchema(user=USER_UNKNOWN_ID), 2, {0: ["user"]}),
            # Built unvalidated, as another caller than the API could. Refused by
            # the null check of `to_internal_values`, so keyed by the index too.
            ("layout set to null", PageUpdateSchema.model_construct(layout=None), 0, {0: ["layout"]}),
            # A dict reaches `to_internal_values` too, where `Field.validate()`
            # enforces the `choices`.
            ("unknown layout", PageUpdateSchema.model_construct(layout="no-such-layout"), 0, {0: ["layout"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": PAGE_SHIRE_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        page = Page.objects.get(pk=PAGE_SHIRE_ID)
        self.assertEqual((page.slug, page.user_id, page.layout), ("shire", UUID(USER_FRODON_ID), LAYOUT_DEFAULT))

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": PAGE_SHIRE_ID}, {"title": "Hobbiton"})

        self.assertEqual(Page.objects.get(pk=PAGE_SHIRE_ID).title, "The Shire")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)({"is_published": True}, PageUpdateSchema(layout="sidebar-right"))

        self.assertEqual(count, 2)
        self.assertCountEqual([page.pk for page in queryset], [PAGE_SHIRE_ID, PAGE_RIVENDELL_ID])
        self.assertEqual(
            dict(Page.objects.values_list("pk", "layout")),
            {PAGE_SHIRE_ID: "sidebar-right", PAGE_MORDOR_ID: LAYOUT_DEFAULT, PAGE_RIVENDELL_ID: "sidebar-right"},
        )

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": PAGE_UNKNOWN_ID}, PageUpdateSchema(title="Isengard"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(Page.objects.filter(title="Isengard").exists())

    @parameterized.expand(
        [
            ("no rule", [], PAGE_MORDOR_ID, True),
            ("own pages, another author's", OWN, PAGE_MORDOR_ID, False),
            ("own pages, one's own", OWN, PAGE_SHIRE_ID, True),
            ("anonymous: no role, no rule", None, PAGE_MORDOR_ID, True),
        ]
    )
    def test_update_access_rules(self, label, rules, pk, reached):
        service = self.service_with_rules(rules)

        count, queryset = async_to_sync(service.update)({"id": pk}, PageUpdateSchema(title="Isengard"))

        # Out of reach is no error: the row is not matched.
        self.assertEqual(count, int(reached))
        self.assertEqual(Page.objects.get(pk=pk).title == "Isengard", reached)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            # Rivendell is the target of no menu item.
            ("a page", {"id": PAGE_RIVENDELL_ID}, 7, 1, [PAGE_SHIRE_ID, PAGE_MORDOR_ID]),
            ("nothing matches", {"id": PAGE_UNKNOWN_ID}, 4, 0, ALL_PAGE_IDS),
        ]
    )
    def test_delete(self, label, filters, query_count, affected, remaining_pks):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertCountEqual(Page.objects.values_list("pk", flat=True), remaining_pks)

    @parameterized.expand(
        [
            # `Menu.page` is PROTECT. `_delete_atomic` maps the `ProtectedError` of
            # the collector, so no raw django exception reaches a controller.
            ("targeted by a menu item", {"id": PAGE_MORDOR_ID}, "Menu.page"),
            # Several pages, one of them protected: nothing is deleted.
            ("among others", {"id__in": [PAGE_MORDOR_ID, PAGE_RIVENDELL_ID]}, "Menu.page"),
        ]
    )
    def test_delete_protected(self, label, filters, relation):
        # Refused by the collector, before any DELETE.
        with self.assertNumQueries(7):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.delete)(filters)

        self.assertEqual(ctx.exception.code, "protected_error")
        # The message names the relation that protects the page.
        self.assertIn(relation, str(ctx.exception.dict()["__all__"]))
        self.assertEqual(Page.objects.count(), 3)

    @parameterized.expand(
        [
            ("no rule", [], True),
            ("own pages, another author's", OWN, False),
            ("anonymous: no role, no rule", None, True),
        ]
    )
    def test_delete_access_rules(self, label, rules, reached):
        service = self.service_with_rules(rules)

        count = async_to_sync(service.delete)({"id": PAGE_RIVENDELL_ID})

        self.assertEqual(count, int(reached))
        self.assertEqual(Page.objects.filter(pk=PAGE_RIVENDELL_ID).exists(), not reached)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def service_with_rules(self, rules, second_role_rules=None):
        """ The service acting as Frodon, whose role holds `rules`; with
        `second_role_rules`, Frodon holds a second role with those. `rules=None`
        is an anonymous caller. """
        if rules is None:
            return self.get_service(PageService)
        self.role.rules = rules
        self.role.save()
        if second_role_rules is not None:
            self.role_hobbit.rules = second_role_rules
            self.role_hobbit.save()
            self.user_frodon.roles.add(self.role_hobbit)
        return self.get_service(PageService, user=self.user_frodon)
