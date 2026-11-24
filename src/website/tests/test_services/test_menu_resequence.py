from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from website.models import Menu
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

# As the common data leaves them.
SEQUENCES = {
    MENU_ROOT_ID: 20,
    MENU_FELLOWSHIP_ID: 10,
    MENU_JOURNEYS_ID: 25,
    MENU_SHIRE_ID: 10,
    MENU_MORDOR_ID: 45,
    MENU_WEST_ID: 30,
}


class MenuResequenceServiceTest(MenuServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Menu`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(MenuService, user=self.user_frodon)

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles, the transaction, the rows found, then one UPDATE whatever
            # their number.
            ("the children of an item", [MENU_MORDOR_ID, MENU_SHIRE_ID], None, 0, 5, {MENU_MORDOR_ID: 1, MENU_SHIRE_ID: 2}),
            # Only the records given are numbered, whatever their place in the tree.
            ("a partial list", [MENU_WEST_ID], None, 0, 5, {MENU_WEST_ID: 1}),
            ("with an offset", [MENU_MORDOR_ID, MENU_SHIRE_ID], None, 20, 5, {MENU_MORDOR_ID: 21, MENU_SHIRE_ID: 22}),
            ("within the filters", [MENU_JOURNEYS_ID, MENU_FELLOWSHIP_ID], {"parent_id": MENU_ROOT_ID}, 0, 5, {MENU_JOURNEYS_ID: 1, MENU_FELLOWSHIP_ID: 2}),
            ("no pk", [], None, 0, 0, {}),
        ]
    )
    def test_resequence(self, label, pks, filters, offset, query_count, expected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.resequence)(pks, filters=filters, offset=offset)

        self.assertEqual(count, len(pks))
        self.assertEqual(dict(Menu.objects.values_list("pk", "sequence")), {**SEQUENCES, **expected})

    @parameterized.expand(
        [
            # All or nothing, and none of these told apart: keyed on `ids`.
            # Refused before any query.
            ("a repeated pk", [MENU_SHIRE_ID, MENU_SHIRE_ID], None, 0),
            ("an unknown pk", [MENU_SHIRE_ID, MENU_UNKNOWN_ID], None, 5),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk", [MENU_SHIRE_ID, "not-a-ulid"], None, 5),
            ("outside the filters", [MENU_SHIRE_ID, MENU_FELLOWSHIP_ID], {"parent_id": MENU_JOURNEYS_ID}, 5),
        ]
    )
    def test_resequence_invalid(self, label, pks, filters, query_count):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.resequence)(pks, filters=filters)

        self.assertEqual(list(ctx.exception.dict()), ["ids"])
        self.assertEqual(dict(Menu.objects.values_list("pk", "sequence")), SEQUENCES)
