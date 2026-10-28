from ninja.errors import HttpError

from authentication.schemas import TokenObtainSchema, TokenPairSchema, TokenRefreshSchema
from authentication.services import AuthService, InvalidCredentials, InvalidRefreshToken
from core.api import BaseController, route
from totem.api import api_v1

__all__ = ["AuthController"]


class AuthController(BaseController):
    """ The exchange of credentials for a token pair, and its rotation.

    A `BaseController` with a service but no model, like
    `saas.api.tenants.TenantController`: a pair of tokens is not a row (see
    `AuthService`). `validate_controllers` only walks `BaseModelController`
    subclasses, so nothing at startup expects CRUD schemas here.

    The only public controller of the project -- `auth = None`, hence
    `Router(auth=None)` and no authentication callback at all. It has to be: this
    is the endpoint one obtains a credential from.

    Permissions deliberately do not go through
    `TokenHasScopePermissionModelControllerMixin`: that mixin maps CRUD
    operations onto scopes, and there is no CRUD operation here. There is no
    scope to check either -- the caller has no identity yet.

    All three views are `async`, as every view of this project is: ninja picks
    the mode of an operation from its view, and a sync one would hand an async
    authentication callback to `async_to_sync` while leaving it un-awaited. These
    routes authenticate nobody, but keeping them async keeps that invariant
    whole.

    ⚠️ Not throttled yet, and `/token/` is the one place in the project where
    unlimited password guesses are possible. ninja throttles natively and
    `core/api/route.py` already forwards `throttle=`, so it is one argument --
    but only meaningful with a cache shared between workers. Immediate follow-up.
    """

    api = api_v1
    path_prefix = "/auth/"
    auth = None

    @route.post(
        "/token/",
        response={200: TokenPairSchema},
        operation_id="authTokenCreate",
        summary="Obtain an access and a refresh token",
        tags=["Authentication"],
    )
    async def token_create(self, request, body: TokenObtainSchema):
        try:
            return await request.env.get(AuthService).login(body.username, body.password)
        except InvalidCredentials:
            # One answer for an unknown login, a wrong password and a disabled
            # account alike: telling them apart is an account enumeration oracle.
            raise HttpError(401, "Invalid credentials.")

    @route.post(
        "/token/refresh/",
        response={200: TokenPairSchema},
        operation_id="authTokenRefresh",
        summary="Exchange a refresh token for a new pair",
        tags=["Authentication"],
    )
    async def token_refresh(self, request, body: TokenRefreshSchema):
        try:
            return await request.env.get(AuthService).refresh(body.refresh_token)
        except InvalidRefreshToken:
            raise HttpError(401, "Invalid refresh token.")

    @route.post(
        "/token/revoke/",
        response={204: None},
        operation_id="authTokenRevoke",
        summary="End the session of a refresh token",
        tags=["Authentication"],
    )
    async def token_revoke(self, request, body: TokenRefreshSchema):
        # 204 whether the token existed or not: the answer must not reveal which
        # refresh secrets are live.
        await request.env.get(AuthService).revoke(body.refresh_token)
