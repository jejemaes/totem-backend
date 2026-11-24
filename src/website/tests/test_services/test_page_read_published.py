from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from website.services import PageService

from website.tests.test_services.common_page import (
    PAGE_MORDOR_ID,
    PAGE_RIVENDELL_ID,
    PAGE_SHIRE_ID,
    PageServiceCommonMixin,
)

OWN = ["website_manage_own_page"]


class PageReadPublishedServiceTest(PageServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `read_published`: what a public visitor may see. Not an access rule: the
    visitor is `user=None`, with no role, so a rule would hold nothing back. """

    def setUp(self):
        super().setUp()
        # What every request of the public site carries.
        self.service = self.get_service(PageService)

    # ------------------------------------------
    # Read Published
    # ------------------------------------------

    @parameterized.expand(
        [
            # No role to read for an anonymous visitor: the pages only.
            ("no filter", None, None, 1, [PAGE_SHIRE_ID, PAGE_RIVENDELL_ID]),
            ("narrowed by the filters", {"slug": "rivendell"}, None, 1, [PAGE_RIVENDELL_ID]),
            # A draft stays out, whatever the filters ask.
            ("a draft asked by its slug", {"slug": "mordor"}, None, 1, []),
            # Pinned as found, worth a fix of its own: the filters are merged
            # over the publication state, so a caller can widen it to the drafts.
            # No caller passes filters a visitor controls today.
            ("the filters override the state", {"is_published": False}, None, 1, [PAGE_MORDOR_ID]),
            ("ordered", None, ["-title"], 1, [PAGE_SHIRE_ID, PAGE_RIVENDELL_ID]),
        ]
    )
    def test_read_published(self, label, filters, ordering, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            pks = [page.pk for page in async_to_sync(self.service.read_published)(filters, ordering=ordering)]

        if ordering:
            self.assertEqual(pks, expected_pks)
        else:
            self.assertCountEqual(pks, expected_pks)

    def test_read_published_fields(self):
        with self.assertNumQueries(1):
            pages = list(async_to_sync(self.service.read_published)({"slug": "shire"}, fields=["id", "title", "slug"]))

        self.assertEqual([page.title for page in pages], ["The Shire"])
        self.assertIn("content", pages[0].get_deferred_fields())

    @parameterized.expand(
        [
            ("no rule", [], [PAGE_SHIRE_ID, PAGE_RIVENDELL_ID]),
            # An author reading through it still has their rules applied on top.
            ("own pages", OWN, [PAGE_SHIRE_ID]),
        ]
    )
    def test_read_published_access_rules(self, label, rules, expected_pks):
        self.role.rules = rules
        self.role.save()
        service = self.get_service(PageService, user=self.user_frodon)

        pks = [page.pk for page in async_to_sync(service.read_published)()]

        self.assertCountEqual(pks, expected_pks)
