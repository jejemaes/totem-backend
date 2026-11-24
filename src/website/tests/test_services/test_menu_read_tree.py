from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
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


class MenuReadTreeServiceTest(MenuServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `read_tree`: the subtree rooted at an item, as a `TreeNode`.

    No access rules tests: no `BaseRule` is registered for `Menu`.
    """

    def setUp(self):
        super().setUp()
        # What the public site carries: the main menu is read by every page.
        self.service = self.get_service(MenuService)

    # ------------------------------------------
    # Read Tree
    # ------------------------------------------

    @parameterized.expand(
        [
            # The children by sequence, at any depth.
            ("a whole tree", MENU_ROOT_ID, [(MENU_FELLOWSHIP_ID, []), (MENU_JOURNEYS_ID, [MENU_SHIRE_ID, MENU_MORDOR_ID])]),
            # A path starts at the top of its tree: rooted on an inner item, the
            # root's own path is read first, then its subtree.
            ("the subtree of an inner item", MENU_JOURNEYS_ID, [(MENU_SHIRE_ID, []), (MENU_MORDOR_ID, [])]),
            ("a root without item", MENU_WEST_ID, []),
            ("a leaf", MENU_SHIRE_ID, []),
        ]
    )
    def test_read_tree(self, label, root_pk, expected_children):
        # The root's path, then the subtree with its pages: the menu URLs read
        # `page.slug` while the template renders, out of reach of any
        # `sync_to_async` hop, so the pages come with the tree.
        with self.assertNumQueries(2):
            node = async_to_sync(self.service.read_tree)(root_pk)
            urls = [child.data.url for child in node.children]

        self.assertEqual(node.data.pk, root_pk)
        # A root of its own tree, even when the record has a parent: the parent
        # sits outside the subtree asked for.
        self.assertIsNone(node.parent)
        self.assertEqual(
            [(child.data.pk, [grandchild.data.pk for grandchild in child.children]) for child in node.children],
            expected_children,
        )
        self.assertEqual(len(urls), len(expected_children))

    def test_read_tree_urls(self):
        node = async_to_sync(self.service.read_tree)(MENU_JOURNEYS_ID)

        self.assertEqual([child.data.url for child in node.children], ["/page/shire/", "/page/mordor/"])

    @parameterized.expand(
        [
            # Degrades rather than raises: the caller may be a widget marker
            # carrying whatever string an author typed.
            ("no pk", None, 0),
            ("an unknown pk", MENU_UNKNOWN_ID, 1),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk", "not-a-ulid", 1),
        ]
    )
    def test_read_tree_not_found(self, label, root_pk, query_count):
        with self.assertNumQueries(query_count):
            self.assertIsNone(async_to_sync(self.service.read_tree)(root_pk))
