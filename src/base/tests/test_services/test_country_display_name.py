from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from base.services import CountryService
from core.testing import ServiceTestCaseMixin

from base.tests.test_services.common_country import CountryServiceCommonMixin


class CountryDisplayNameServiceTest(CountryServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Country`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(CountryService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the countries.
            ("one pk", ["GD"], 2, ["GD"]),
            ("in the order of the pks", ["RH", "SH"], 2, ["RH", "SH"]),
            ("a repeated pk appears once", ["GD", "GD"], 2, ["GD"]),
            ("an unknown pk is absent", ["MO", "GD"], 2, ["GD"]),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            countries = async_to_sync(self.service.display_name)(pks, ["code", "name"])

        self.assertEqual([country.pk for country in countries], expected_pks)
