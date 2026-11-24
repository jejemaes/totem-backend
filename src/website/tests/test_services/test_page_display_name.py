from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from website.services import PageService

from website.tests.test_services.common_page import (
    PAGE_MORDOR_ID,
    PAGE_RIVENDELL_ID,
    PAGE_SHIRE_ID,
    PAGE_UNKNOWN_ID,
    PageServiceCommonMixin,
)

OWN = ["website_manage_own_page"]


class PageDisplayNameServiceTest(PageServiceCommonMixin, ServiceTestCaseMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.service = self.get_service(PageService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the pages.
            ("one pk", [PAGE_MORDOR_ID], 2, [PAGE_MORDOR_ID]),
            ("in the order of the pks", [PAGE_RIVENDELL_ID, PAGE_SHIRE_ID], 2, [PAGE_RIVENDELL_ID, PAGE_SHIRE_ID]),
            ("a repeated pk appears once", [PAGE_MORDOR_ID, PAGE_MORDOR_ID], 2, [PAGE_MORDOR_ID]),
            ("an unknown pk is absent", [PAGE_UNKNOWN_ID, PAGE_MORDOR_ID], 2, [PAGE_MORDOR_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            pages = async_to_sync(self.service.display_name)(pks, ["id", "title", "slug"])

        self.assertEqual([page.pk for page in pages], expected_pks)
        for page in pages:
            self.assertFalse({"title", "slug"} & page.get_deferred_fields())
            self.assertIn("content", page.get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], [PAGE_SHIRE_ID, PAGE_MORDOR_ID]),
            ("own pages", OWN, [PAGE_SHIRE_ID]),
            ("anonymous: no role, no rule", None, [PAGE_SHIRE_ID, PAGE_MORDOR_ID]),
        ]
    )
    def test_display_name_access_rules(self, label, rules, expected_pks):
        if rules is None:
            service = self.get_service(PageService)
        else:
            self.role.rules = rules
            self.role.save()
            service = self.get_service(PageService, user=self.user_frodon)

        pages = async_to_sync(service.display_name)([PAGE_SHIRE_ID, PAGE_MORDOR_ID], ["id", "title"])

        # Out of reach and unknown are told apart by nothing: both are absent.
        self.assertEqual([page.pk for page in pages], expected_pks)
