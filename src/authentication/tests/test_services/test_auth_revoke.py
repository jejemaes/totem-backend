from asgiref.sync import async_to_sync
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from authentication.models import RefreshToken
from authentication.services import AuthService, InvalidRefreshToken
from core.testing import ServiceTestCaseMixin

from authentication.tests.test_services.common_auth import PASSWORD, AuthServiceCommonMixin


@freeze_time("2024-11-18 11:12:13")
class AuthRevokeServiceTest(AuthServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `revoke`: sign out. The session ends, not just the token presented. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(AuthService)
        self.first = async_to_sync(self.service.login)("frodon@lacomte.com", PASSWORD)
        self.second = async_to_sync(self.service.refresh)(self.first.refresh_token)
        self.other_session = async_to_sync(self.service.login)("frodon@lacomte.com", PASSWORD)

    # ------------------------------------------
    # Revoke
    # ------------------------------------------

    @parameterized.expand(
        [
            ("the live token", "second"),
            # The whole chain, whichever of its tokens is presented.
            ("a spent token of the session", "first"),
        ]
    )
    def test_revoke(self, label, presented):
        # The token found, then the revocation of its session.
        with self.assertNumQueries(2):
            result = async_to_sync(self.service.revoke)(getattr(self, presented).refresh_token)

        self.assertIsNone(result)
        with self.assertRaises(InvalidRefreshToken):
            async_to_sync(self.service.refresh)(self.second.refresh_token)
        # Another session is another chain: it is left alone.
        self.assertEqual(RefreshToken.objects.active().count(), 1)

    def test_revoke_unknown(self):
        # Says nothing: the endpoint answers the same either way, so a caller
        # cannot probe which secrets are live.
        with self.assertNumQueries(1):
            self.assertIsNone(async_to_sync(self.service.revoke)("never-issued"))

        self.assertEqual(RefreshToken.objects.active().count(), 2)
