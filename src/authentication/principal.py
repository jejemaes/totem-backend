"""The common contract of whatever ends up in `request.auth`.

Each authenticator returns its own object -- `JWTAuth` an `AccessToken`,
`ApiKeyAuth` the `ApiKey` row itself -- rather than one catch-all type. The two
have nothing in common beyond what the authorization layer reads from them, and
`ScopedPrincipalMixin` is exactly that: `user`, `scopes`, `has_scopes`.

This module imports nothing of the project on purpose (the `User` annotation is
a string): `authentication.models.api_key` imports the mixin, so anything
imported here would be imported before the app registry is ready.
"""

import dataclasses
import datetime
import typing as t

__all__ = ["AccessToken", "ScopedPrincipalMixin"]


class ScopedPrincipalMixin:
    """ What the authorization layer may assume of `request.auth`.

    Subclasses provide `scopes`. `user` stays `None` for a machine caller, which
    is what `Request._get_request_user` and `IsAuthenticated` test for -- a
    machine caller is authenticated but is nobody, and the difference matters:
    `/users/me/` has no answer for it.
    """

    # A machine caller has no user. A class attribute rather than a field, so a
    # model mixing this in needs no column and no migration for it.
    user = None

    @property
    def scopes(self) -> t.Set[str]:
        raise NotImplementedError

    @property
    def is_authenticated(self) -> bool:
        """ Holding this object at all means the credential was verified. """
        return True

    def has_scopes(self, scopes) -> bool:
        """ Whether every one of `scopes` was granted.

        An empty requirement is granted: a route that declares no scope asks for
        authentication only. That is the semantics DOT's `allow_scopes` had, and
        changing it would silently open or close routes.

        Expiry is deliberately not rechecked here. It was already proven, before
        this object could exist, by the signature check (`decode_access_token`)
        or by the `expires_at` filter of the lookup (`ApiKeyQuerySet.usable`).
        """
        if not scopes:
            return True
        return set(scopes).issubset(self.scopes)


@dataclasses.dataclass(frozen=True, slots=True)
class AccessToken(ScopedPrincipalMixin):
    """ A decoded and verified JWT. Never persisted, hence the value object.

    Carries the attribute names `request.auth` had under DOT (`user`, `scope`),
    which is why the controllers, `access_policy` and the test stub needed no
    translation when the dependency went away.
    """

    # `field()` with no default, rather than a bare annotation: `dataclasses`
    # looks a default up with `getattr(cls, name)`, which would find the `None`
    # the mixin sets as a class attribute and make every field after this one
    # follow a defaulted one. An explicit empty `field()` shadows it and keeps
    # `user` required.
    user: "User" = dataclasses.field()  # noqa: F821 -- annotation only, see the module docstring
    scope: str = dataclasses.field()  # space-separated, as the `scope` claim stores it
    jti: str
    expires_at: datetime.datetime

    @property
    def scopes(self) -> t.Set[str]:
        return set(self.scope.split())
