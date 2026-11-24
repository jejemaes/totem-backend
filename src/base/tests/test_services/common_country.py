from base.models import Country
from user.tests.test_services.common_user import UserServiceCommonMixin


class CountryServiceCommonMixin(UserServiceCommonMixin):
    """ Three countries, on top of the users of `user`: The Shire (SH), Gondor
    (GD) and Rohan (RH). The pk of a country is its code. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.country_shire, cls.country_gondor, cls.country_rohan = Country.objects.bulk_create([
            Country(code="SH", name="The Shire"),
            Country(code="GD", name="Gondor"),
            Country(code="RH", name="Rohan"),
        ])
