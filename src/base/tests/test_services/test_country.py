from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from base.services import CountryService
from core.testing import ServiceTestCaseMixin

from base.tests.test_services.common_country import CountryServiceCommonMixin


class CountryServiceTest(CountryServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `CountryService` is read-only: the countries come from the system fixture.

    No access rules tests: no `BaseRule` is registered for `Country`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(CountryService, user=self.user_frodon)

    # ------------------------------------------
    # Create, Update, Delete
    # ------------------------------------------

    @parameterized.expand([("create",), ("default_values",), ("update",), ("delete",), ("resequence",)])
    def test_operation_is_not_composed(self, operation):
        # The controller exposes no write route; the service must not offer one
        # either, or a hand-written `@route` could bypass that decision.
        self.assertFalse(hasattr(CountryService, operation))

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ["SH", "GD", "RH"]),
            ("by code", {"code": "GD"}, ["GD"]),
            ("by name", {"name__icontains": "o"}, ["GD", "RH"]),
            ("nothing matches", {"code": "MO"}, []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        # The roles of the acting user, then the countries.
        with self.assertNumQueries(2):
            pks = [country.pk for country in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by name", ["name"], ["GD", "RH", "SH"]),
            ("by name, descending", ["-name"], ["SH", "RH", "GD"]),
            ("by code", ["code"], ["GD", "RH", "SH"]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [country.pk for country in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    def test_read_anonymous(self):
        # What the public site carries: no role to read, the countries only.
        with self.assertNumQueries(1):
            pks = [country.pk for country in async_to_sync(self.get_service(CountryService).read)()]

        self.assertCountEqual(pks, ["SH", "GD", "RH"])
