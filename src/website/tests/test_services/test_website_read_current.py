from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from website.models import Website
from website.services import WebsiteService

from website.tests.test_services.common_website import WEBSITE_ID, WebsiteServiceCommonMixin

# Sorts before and after `WEBSITE_ID`.
WEBSITE_BEFORE_ID = "01M209K5BNS12QRPHXFWVJNVD0"
WEBSITE_AFTER_ID = "01M209K5BNS12QRPHXFWVJNVD2"


class WebsiteReadCurrentServiceTest(WebsiteServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `read_current`: the website record every page of the public site reads. """

    def setUp(self):
        super().setUp()
        # What every request of the public site carries: no user, no role.
        self.service = self.get_service(WebsiteService)

    # ------------------------------------------
    # Read Current
    # ------------------------------------------

    @parameterized.expand(
        [
            # No role to read for an anonymous visitor: the row only.
            ("the row", [], WEBSITE_ID),
            # Nothing forbids a second row, so the read cannot depend on the
            # planner: the first by pk.
            ("a second row after it", [WEBSITE_AFTER_ID], WEBSITE_ID),
            ("a second row before it", [WEBSITE_BEFORE_ID], WEBSITE_BEFORE_ID),
        ]
    )
    def test_read_current(self, label, other_ids, expected_pk):
        Website.objects.bulk_create([Website(id=pk, name="Arda", headline="Elder Days") for pk in other_ids])

        with self.assertNumQueries(1):
            website = async_to_sync(self.service.read_current)()

        self.assertEqual(website.pk, expected_pk)

    def test_read_current_unpopulated(self):
        # `/` must answer on a fresh install: None, not an error.
        Website.objects.all().delete()

        with self.assertNumQueries(1):
            self.assertIsNone(async_to_sync(self.service.read_current)())

    def test_read_current_fields(self):
        # Only the controller passes `fields`: on the render path, one name
        # missing would raise inside the template.
        with self.assertNumQueries(1):
            website = async_to_sync(self.service.read_current)(fields=["id", "name"])

        self.assertEqual(website.name, "Middle-earth")
        self.assertIn("footer", website.get_deferred_fields())

    @parameterized.expand(
        [
            # A rule of another model holds nothing back here: no `BaseRule` is
            # registered for `Website`, which is what lets the public site read it.
            ("a user with a rule of the pages", ["website_manage_own_page"]),
            ("a user without rule", []),
        ]
    )
    def test_read_current_access_rules(self, label, rules):
        self.role.rules = rules
        self.role.save()
        service = self.get_service(WebsiteService, user=self.user_frodon)

        self.assertEqual(async_to_sync(service.read_current)().pk, WEBSITE_ID)
