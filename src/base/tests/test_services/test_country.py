from asgiref.sync import async_to_sync
from django.test import TestCase

from base.models import Country
from base.services import CountryService
from core.services import Environment


class TestCountryService(TestCase):

    @classmethod
    def setUpTestData(cls):
        Country.objects.bulk_create([
            Country(code="BE", name="Belgium"),
            Country(code="FR", name="France"),
            Country(code="NL", name="Netherlands"),
        ])

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(CountryService)

    def test_read_all(self):
        queryset = async_to_sync(self.service.read)(None)

        self.assertEqual(
            sorted(country.pk for country in queryset), ["BE", "FR", "NL"]
        )

    def test_read_with_filters(self):
        queryset = async_to_sync(self.service.read)({"code": "BE"})

        self.assertEqual([country.name for country in queryset], ["Belgium"])

    def test_read_with_ordering(self):
        queryset = async_to_sync(self.service.read)(None, ordering=["-name"])

        self.assertEqual(
            [country.pk for country in queryset], ["NL", "FR", "BE"]
        )

    def test_service_is_read_only(self):
        # The controller exposes no write route; the service must not offer one
        # either, otherwise a hand-written `@route` could bypass that decision.
        for operation in ("create", "update", "delete"):
            self.assertFalse(
                hasattr(self.service, operation),
                f"CountryService should not provide `{operation}`.",
            )
