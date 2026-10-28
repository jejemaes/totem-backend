from authentication.models import ApiKey
from authentication.testing import AccessTokenStub, public_scopes
from authentication.tokens import hash_secret
from user import choices as user_choices
from user.models import User, UserRole

USER_ID1 = "c99199ba-8fa5-461e-802e-c303e390f61b"
USER_ID2 = "401ac0f2-4abe-412c-acf8-9928f0f53edb"
USER_ID3 = '8632bc93-e692-43de-b873-34610551afcd'

API_KEY_SECRET = "a-machine-caller-secret"


class CommonTestMixin:
    """ The users, roles and credentials every API test case builds on.

    The access tokens are `AccessTokenStub`s, not rows: an access token is a
    signed JWT with no database row behind it, so there is nothing to create.
    The stub mints a real token from the production encoder on each access to
    `.token`, which is what lets a test assign `.scope` and call `.save()` -- as
    the parameterized access-rights tests do -- with nothing persisted.

    `api_key`, on the other hand, is a real row: a key *is* a record. It holds
    every scope a key *may* hold -- `public_scopes()`, not `all_scopes()`, since
    `totem.apikey.*` is one no key can ever be granted -- so what a test
    exercises with it is the authenticator and the scope check, never a missing
    grant.
    """

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

        cls.user_access_token_frodon = AccessTokenStub(user=cls.user_frodon)
        cls.user_access_token_gollum = AccessTokenStub(user=cls.user_gollum)

        # The machine caller. Replaces the client-credentials token of the
        # toolkit, which no test ever used -- which is precisely why
        # `Request._get_request_user` could fall back to `AnonymousUser`
        # unnoticed.
        cls.api_key = ApiKey.objects.create(
            name="Test Machine Caller",
            secret_hash=hash_secret(API_KEY_SECRET),
            scope=public_scopes(),
        )
        cls.api_key_secret = API_KEY_SECRET
