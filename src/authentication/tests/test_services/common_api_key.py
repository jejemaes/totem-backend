from authentication.models import ApiKey
from user.tests.test_services.common_user import UserServiceCommonMixin

KEY_ARCHIVE_ID = "01JQ0000000000000000000001"
KEY_PALANTIR_ID = "01JQ0000000000000000000002"

KEY_UNKNOWN_ID = "01JQ0000000000000000000099"


class ApiKeyServiceCommonMixin(UserServiceCommonMixin):
    """ Two keys, on top of the users of `user`: "Red Book Archive", reading the
    users, and "Palantír", revoked, with no scope. Bulk created, so their secrets
    are derived by `ApiKeyQuerySet.bulk_create`, and then forgotten. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.key_archive, cls.key_palantir = ApiKey.objects.bulk_create([
            ApiKey(id=KEY_ARCHIVE_ID, name="Red Book Archive", scope=["totem.user.read"]),
            ApiKey(id=KEY_PALANTIR_ID, name="Palantír", is_active=False),
        ])
