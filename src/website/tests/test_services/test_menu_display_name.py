from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from website.services import MenuService

from website.tests.test_services.common_menu import (
    MENU_JOURNEYS_ID,
    MENU_ROOT_ID,
    MENU_SHIRE_ID,
    MENU_UNKNOWN_ID,
    MenuServiceCommonMixin,
)


class MenuDisplayNameServiceTest(MenuServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Menu`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(MenuService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the items.
            ("one pk", [MENU_SHIRE_ID], 2, [MENU_SHIRE_ID]),
            ("in the order of the pks", [MENU_SHIRE_ID, MENU_ROOT_ID], 2, [MENU_SHIRE_ID, MENU_ROOT_ID]),
            ("a repeated pk appears once", [MENU_SHIRE_ID, MENU_SHIRE_ID], 2, [MENU_SHIRE_ID]),
            ("an unknown pk is absent", [MENU_UNKNOWN_ID, MENU_SHIRE_ID], 2, [MENU_SHIRE_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            menus = async_to_sync(self.service.display_name)(pks, ["id", "name"])

        self.assertEqual([menu.pk for menu in menus], expected_pks)
        for menu in menus:
            self.assertNotIn("name", menu.get_deferred_fields())
            self.assertIn("link", menu.get_deferred_fields())

    def test_display_name_filters(self):
        # The path of a nested route narrows them further.
        menus = async_to_sync(self.service.display_name)([MENU_SHIRE_ID, MENU_ROOT_ID], ["id", "name"], filters={"parent_id": MENU_JOURNEYS_ID})

        self.assertEqual([menu.pk for menu in menus], [MENU_SHIRE_ID])
