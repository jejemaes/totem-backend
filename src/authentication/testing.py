"""Credential helpers for the tests of every app.

Named `testing` rather than `tests` or `test_*` on purpose: the runner collects
anything matching `test*`, and would try to run this module as a test case.
"""

from authentication.tokens import encode_access_token
from user.access_rights import get_all_permission

__all__ = ["AccessTokenStub", "all_scopes", "mint_access_token"]


def all_scopes():
    """ Every registered permission, the non-public ones included.

    What a test that wants "a token allowed to do everything" needs. Reads the
    registry rather than a literal list, so a permission added by a new app is
    covered without touching any fixture.
    """
    return [permission for permission, dummy in get_all_permission()]


def mint_access_token(user, scopes=None, *, ttl=None, now=None) -> str:
    """ A real access token for `user`, signed by the production encoder.

    Nothing about the format is simulated, which is the point: a test that passes
    here passes against the same codec the authenticator runs.
    """
    token, dummy = encode_access_token(
        user.pk, all_scopes() if scopes is None else scopes, ttl=ttl, now=now
    )
    return token


class AccessTokenStub:
    """ Stands in for the database row the API tests used to build.

    Carries the attributes of the production `AccessToken` (`user`, `scope`) plus
    a `token` minted on *access*, so that the access-rights tests -- which assign
    `scope` and then call `save()` -- keep working with nothing persisted. That is
    why `token` is a property and `save()` a no-op: the shape of the old API is
    kept, the row is not.
    """

    def __init__(self, user=None, scope=None):
        self.user = user
        self.scope = " ".join(all_scopes()) if scope is None else scope

    @property
    def token(self) -> str:
        return mint_access_token(self.user, self.scope.split())

    def save(self, *args, **kwargs):
        return None
