from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from website.models import Menu
from website.schemas import MenuCreateSchema, MenuFilterSchema, MenuUpdateSchema
from website.services import MenuService

from website.tests.test_services.common_menu import (
    MENU_FELLOWSHIP_ID,
    MENU_JOURNEYS_ID,
    MENU_MORDOR_ID,
    MENU_ROOT_ID,
    MENU_SHIRE_ID,
    MENU_UNKNOWN_ID,
    MENU_WEST_ID,
    MenuServiceCommonMixin,
)
from website.tests.test_services.common_page import PAGE_RIVENDELL_ID, PAGE_SHIRE_ID, PAGE_UNKNOWN_ID

ALL_MENU_IDS = [MENU_ROOT_ID, MENU_FELLOWSHIP_ID, MENU_JOURNEYS_ID, MENU_SHIRE_ID, MENU_MORDOR_ID, MENU_WEST_ID]

# As the common data leaves them.
PATHS = {
    MENU_ROOT_ID: f"{MENU_ROOT_ID}/",
    MENU_FELLOWSHIP_ID: f"{MENU_ROOT_ID}/{MENU_FELLOWSHIP_ID}/",
    MENU_JOURNEYS_ID: f"{MENU_ROOT_ID}/{MENU_JOURNEYS_ID}/",
    MENU_SHIRE_ID: f"{MENU_ROOT_ID}/{MENU_JOURNEYS_ID}/{MENU_SHIRE_ID}/",
    MENU_MORDOR_ID: f"{MENU_ROOT_ID}/{MENU_JOURNEYS_ID}/{MENU_MORDOR_ID}/",
    MENU_WEST_ID: f"{MENU_WEST_ID}/",
}

LINK_OR_PAGE = "Menu must be linked to an URL or a page."


class MenuServiceTest(MenuServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `MenuService`: create, read, update, delete. `parent_path` is kept by
    `MenuQuerySet` on every write: each test reads the paths back.

    No access rules tests: no `BaseRule` is registered for `Menu`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(MenuService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # `parent_path` is not null and has no default: the service inserts
            # through `bulk_create`, which never calls the `save()` computing it.
            ("a root", {"name": "Rohan"}, 5, [], {"link": None, "page_id": None}),
            # The constraint exempts the roots: containers, not destinations.
            ("a child with a link", {"name": "Bree", "parent": MENU_ROOT_ID, "link": "/bree/"}, 6, [MENU_ROOT_ID], {"link": "/bree/"}),
            # The page is resolved through its service.
            (
                "a grandchild with a page",
                {"name": "Rivendell", "parent": MENU_JOURNEYS_ID, "page": PAGE_RIVENDELL_ID, "sequence": 5},
                7,
                [MENU_ROOT_ID, MENU_JOURNEYS_ID],
                {"page_id": PAGE_RIVENDELL_ID, "sequence": 5},
            ),
        ]
    )
    def test_create(self, label, payload, query_count, ancestors, expected_values):
        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([MenuCreateSchema(**payload)])

        self.assertEqual([menu.name for menu in instances], [payload["name"]])
        menu = Menu.objects.get(pk=instances[0].pk)
        self.assertEqual(menu.parent_path, "".join(f"{pk}/" for pk in [*ancestors, menu.pk]))
        self.assertEqual({name: getattr(menu, name) for name in expected_values}, expected_values)

    @parameterized.expand(
        [
            # `menu_page_or_link`, surfaced through its `violation_error_message`.
            ("a child without link or page", {"name": "Bree", "parent": MENU_ROOT_ID}, 6, LINK_OR_PAGE),
        ]
    )
    def test_create_invalid(self, label, payload, query_count, message):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([MenuCreateSchema(**payload)])

        self.assertEqual(ctx.exception.dict(), {"__all__": {"__all__": [message]}})
        self.assertEqual(Menu.objects.count(), 6)

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"name": "Rohan"}])

        self.assertEqual(Menu.objects.count(), 6)

    @parameterized.expand(
        [
            # The roles, then one query per relation given.
            ("unknown parent", {"parent": MENU_UNKNOWN_ID, "link": "/bree/"}, 2, "parent"),
            ("unknown page", {"parent": MENU_ROOT_ID, "page": PAGE_UNKNOWN_ID}, 3, "page"),
        ]
    )
    def test_create_relations(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([MenuCreateSchema(name="Bree", **values)])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Menu.objects.count(), 6)

    @parameterized.expand(
        [
            ("every input valid", [{"name": "Rohan"}, {"name": "Bree", "parent": MENU_ROOT_ID, "link": "/bree/"}], 6, None),
            # All or nothing: the valid first input is not written either.
            ("the second input invalid", [{"name": "Rohan"}, {"name": "Bree", "parent": MENU_ROOT_ID}], 6, "__all__"),
        ]
    )
    def test_create_batch(self, label, payloads, query_count, error_key):
        data = [MenuCreateSchema(**payload) for payload in payloads]

        with self.assertNumQueries(query_count):
            if error_key is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if error_key is None:
            self.assertEqual([menu.name for menu in instances], ["Rohan", "Bree"])
            self.assertEqual(Menu.objects.count(), 8)
        else:
            self.assertEqual(list(ctx.exception.dict()), [error_key])
            self.assertFalse(Menu.objects.filter(name="Rohan").exists())

    @parameterized.expand(
        [
            ("every field", None, {"sequence": 20, "new_window": False}),
            ("the fields asked", ["sequence", "parent"], {"sequence": 20}),
        ]
    )
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, expected)

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_MENU_IDS),
            # The filter schema of the API, with its own lookups.
            ("a whole tree", MenuFilterSchema(root=MENU_ROOT_ID), [MENU_ROOT_ID, MENU_FELLOWSHIP_ID, MENU_JOURNEYS_ID, MENU_SHIRE_ID, MENU_MORDOR_ID]),
            # Pinned as found, worth a fix of its own: a path starts at the top of
            # its tree, so an inner ancestor is the prefix of nothing -- the bug
            # `read_tree` was fixed of, still in this filter.
            ("the subtree of an inner item", MenuFilterSchema(root=MENU_JOURNEYS_ID), []),
            ("the direct children", MenuFilterSchema(parent=[MENU_ROOT_ID]), [MENU_FELLOWSHIP_ID, MENU_JOURNEYS_ID]),
            ("the top-level items", MenuFilterSchema(parent=["null"]), [MENU_ROOT_ID, MENU_WEST_ID]),
            ("by target page", MenuFilterSchema(target_page=[PAGE_SHIRE_ID]), [MENU_SHIRE_ID]),
            ("by a search term in the link", MenuFilterSchema(search="fellow"), [MENU_FELLOWSHIP_ID]),
            ("nothing matches", MenuFilterSchema(name="Isengard"), []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [menu.pk for menu in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by sequence, then name", ["sequence", "name"], [MENU_FELLOWSHIP_ID, MENU_SHIRE_ID, MENU_ROOT_ID, MENU_JOURNEYS_ID, MENU_WEST_ID, MENU_MORDOR_ID]),
            # The materialized path orders a tree depth first.
            ("by path", ["parent_path"], [MENU_ROOT_ID, MENU_FELLOWSHIP_ID, MENU_JOURNEYS_ID, MENU_SHIRE_ID, MENU_MORDOR_ID, MENU_WEST_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [menu.pk for menu in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "name"], 2, None),
            # The page is prefetched, with the fields asked on it.
            ("the target page", ["id", "page__slug"], 3, "shire"),
        ]
    )
    def test_read_fields(self, label, fields, query_count, slug):
        with self.assertNumQueries(query_count):
            menus = list(async_to_sync(self.service.read)({"id": MENU_SHIRE_ID}, fields=fields))
            loaded = menus[0].page.slug if slug else None

        self.assertEqual(loaded, slug)
        self.assertIn("link", menus[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            # A plain field leaves the paths alone; a move recomputes them.
            ("the name", MENU_JOURNEYS_ID, {"name": "Roads"}, 5, {}),
            # The moved row and everything below it: the recursive recompute is
            # what makes the descendants follow.
            (
                "moved under another root",
                MENU_JOURNEYS_ID,
                {"parent": MENU_WEST_ID},
                7,
                {
                    MENU_JOURNEYS_ID: f"{MENU_WEST_ID}/{MENU_JOURNEYS_ID}/",
                    MENU_SHIRE_ID: f"{MENU_WEST_ID}/{MENU_JOURNEYS_ID}/{MENU_SHIRE_ID}/",
                    MENU_MORDOR_ID: f"{MENU_WEST_ID}/{MENU_JOURNEYS_ID}/{MENU_MORDOR_ID}/",
                },
            ),
            (
                "unparented: a root",
                MENU_JOURNEYS_ID,
                {"parent": None},
                6,
                {
                    MENU_JOURNEYS_ID: f"{MENU_JOURNEYS_ID}/",
                    MENU_SHIRE_ID: f"{MENU_JOURNEYS_ID}/{MENU_SHIRE_ID}/",
                    MENU_MORDOR_ID: f"{MENU_JOURNEYS_ID}/{MENU_MORDOR_ID}/",
                },
            ),
            ("a leaf moved up", MENU_SHIRE_ID, {"parent": MENU_ROOT_ID}, 7, {MENU_SHIRE_ID: f"{MENU_ROOT_ID}/{MENU_SHIRE_ID}/"}),
        ]
    )
    def test_update(self, label, pk, payload, query_count, moved_paths):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": pk}, MenuUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([menu.pk for menu in queryset], [pk])
        self.assertEqual(dict(Menu.objects.values_list("pk", "parent_path")), {**PATHS, **moved_paths})
        if "name" in payload:
            self.assertEqual(Menu.objects.get(pk=pk).name, payload["name"])

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": MENU_FELLOWSHIP_ID}, MenuUpdateSchema(new_window=True))

        menu = Menu.objects.get(pk=MENU_FELLOWSHIP_ID)
        self.assertEqual(
            (menu.name, menu.link, menu.sequence, menu.parent_id, menu.new_window),
            ("The Fellowship", "/fellowship/", 10, MENU_ROOT_ID, True),
        )

    @parameterized.expand(
        [
            # `validate_data` during an update: keyed by the pk of the record.
            ("its own parent", MENU_JOURNEYS_ID, MenuUpdateSchema(parent=MENU_JOURNEYS_ID), 6, {MENU_JOURNEYS_ID: ["parent"]}),
            # Without the guard, no error downstream: the recompute walks down from
            # the roots, so the cycled rows keep a stale path and vanish from
            # every tree read.
            ("under its own child", MENU_JOURNEYS_ID, MenuUpdateSchema(parent=MENU_SHIRE_ID), 6, {MENU_JOURNEYS_ID: ["parent"]}),
            ("under its own grandchild", MENU_ROOT_ID, MenuUpdateSchema(parent=MENU_MORDOR_ID), 6, {MENU_ROOT_ID: ["parent"]}),
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown parent", MENU_JOURNEYS_ID, MenuUpdateSchema(parent=MENU_UNKNOWN_ID), 2, {0: ["parent"]}),
            # The constraint of the table: keyed on nobody.
            ("a child losing its link", MENU_FELLOWSHIP_ID, MenuUpdateSchema(link=None), 6, {"__all__": ["__all__"]}),
        ]
    )
    def test_update_invalid(self, label, pk, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": pk}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        self.assertEqual(dict(Menu.objects.values_list("pk", "parent_path")), PATHS)
        self.assertEqual(Menu.objects.get(pk=MENU_FELLOWSHIP_ID).link, "/fellowship/")

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": MENU_ROOT_ID}, {"name": "Arda"})

        self.assertEqual(Menu.objects.get(pk=MENU_ROOT_ID).name, "Middle-earth")

    def test_update_batch(self):
        with self.assertNumQueries(5):
            count, queryset = async_to_sync(self.service.update)(
                MenuFilterSchema(parent=[MENU_JOURNEYS_ID]), MenuUpdateSchema(new_window=True)
            )

        self.assertEqual(count, 2)
        self.assertCountEqual([menu.pk for menu in queryset], [MENU_SHIRE_ID, MENU_MORDOR_ID])
        self.assertCountEqual(Menu.objects.filter(new_window=True).values_list("pk", flat=True), [MENU_SHIRE_ID, MENU_MORDOR_ID])

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": MENU_UNKNOWN_ID}, MenuUpdateSchema(name="Isengard"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(Menu.objects.filter(name="Isengard").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a leaf", {"id": MENU_FELLOWSHIP_ID}, 7, 1),
            ("a root without item", {"id": MENU_WEST_ID}, 7, 1),
            ("nothing matches", {"id": MENU_UNKNOWN_ID}, 4, 0),
        ]
    )
    def test_delete(self, label, filters, query_count, affected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(Menu.objects.count(), 6 - affected)
        self.assertFalse(Menu.objects.filter(**filters).exists())

    @parameterized.expand(
        [
            # `Menu.parent` is PROTECT: an item with children stays.
            ("an item with children", {"id": MENU_JOURNEYS_ID}, "Menu.parent"),
            # Even with its children in the same delete. Pinned as found.
            ("a whole subtree at once", {"parent_path__startswith": f"{MENU_ROOT_ID}/{MENU_JOURNEYS_ID}/"}, "Menu.parent"),
        ]
    )
    def test_delete_protected(self, label, filters, relation):
        # Refused by the collector, before any DELETE.
        with self.assertNumQueries(6):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.delete)(filters)

        self.assertEqual(ctx.exception.code, "protected_error")
        self.assertIn(relation, str(ctx.exception.dict()["__all__"]))
        self.assertEqual(Menu.objects.count(), 6)
