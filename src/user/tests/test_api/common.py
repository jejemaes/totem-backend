from datetime import timedelta

from django.utils import timezone
from oauth2_provider.scopes import get_scopes_backend

from oauth.models import AccessToken, OAuthApp
from user import choices as user_choices
from user.models import User, UserRole

USER_ID1 = "c99199ba-8fa5-461e-802e-c303e390f61b"
USER_ID2 = "401ac0f2-4abe-412c-acf8-9928f0f53edb"
USER_ID3 = '8632bc93-e692-43de-b873-34610551afcd'

OAUTH_APP_ID = "87940016-4354-40cb-ac7d-7434f59d0f94"


class CommonTestMixin:

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role = UserRole.objects.create(id="TEST_BASEUSER", name="Role Test (Base)")

        cls.user_frodon = User.objects.create(
            id=USER_ID1,
            username="frodon@lacomte.com",
            email="frodon@lacomte.com",
            first_name="Frodon",
            user_type=user_choices.UserType.INTERNAL,
        )
        cls.user_gollum = User.objects.create(
            id=USER_ID2,
            username="gollum@precious.com",
            email="gollum@precious.com",
            user_type=user_choices.UserType.PORTAL,
        )

        cls.user_frodon.roles.set([cls.role])
        cls.user_gollum.roles.set([cls.role])

        cls.oauth_app = OAuthApp.objects.create(
            id=OAUTH_APP_ID,
            name="Application for Test",
            client_type=OAuthApp.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApp.GRANT_CLIENT_CREDENTIALS,
            redirect_uris="",  # value when creation through django DOT form on /o/applications/
            skip_authorization=False,
        )
        cls.app_access_token = AccessToken.objects.create(
            application=cls.oauth_app,
            token="lacomte_secure_token",
            scope=" ".join(get_scopes_backend().get_all_scopes().keys()),
            expires=timezone.now() + timedelta(days=365),
        )
        cls.user_access_token_frodon = AccessToken.objects.create(
            user=cls.user_frodon,
            token="frodon_secure_token",
            scope=" ".join(
                list(get_scopes_backend().get_all_scopes())
            ),
            expires=timezone.now() + timedelta(days=365),
        )
        cls.user_access_token_gollum = AccessToken.objects.create(
            user=cls.user_gollum,
            token="gollum_secure_token",
            scope=" ".join(
                list(get_scopes_backend().get_all_scopes())
            ),
            expires=timezone.now() + timedelta(days=365),
        )
