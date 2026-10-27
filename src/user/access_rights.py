import re
from collections import namedtuple

from django.core.exceptions import ImproperlyConfigured


__all__ = [
    "register_permission",
    "get_all_permission",
    "get_public_permission",
    "get_permission_choices",
    "get_user_scopes",
]


# Private registry with all permission of the system
_PERMISSIONS = {}

# Internal format for permission
PermissionRecord = namedtuple(
    "PermissionRecord", ["permission", "description", "is_public"]
)

# Regex of permission name
regex = r"[a-z]{3,}\.[a-z]{3,}\.[a-z]{3,}"


def register_permission(permission, description, is_public=False):
    """
        :param is_public: can be selectable for API token through the public API
    """
    if permission in _PERMISSIONS:
        raise ImproperlyConfigured(f"The permission {permission} already exists.")
    if re.match(regex, permission) is None:
        raise ImproperlyConfigured(f"The permission name {permission} does not match the regex.")
    _PERMISSIONS[permission] = PermissionRecord(permission, description, is_public)


def get_all_permission():
    """ Get the all permission, associated with ther description. """
    result = []
    for perm, record in _PERMISSIONS.items():
        result.append((perm, record.description))
    return result


def get_public_permission():
    """ Get the public list of permission, associated with ther description. """
    result = []
    for perm, record in _PERMISSIONS.items():
        if record.is_public:
            result.append((perm, record.description))
    return result


def get_permission_choices():
    result = []
    for perm, record in _PERMISSIONS.items():
        result.append((perm, record.permission))
    return result


def get_user_scopes(user):
    """ The permissions granted to a user: the union of those of their roles.

    Sorted, so that the `scope` claim of an access token is deterministic: two
    tokens minted from the same roles carry the same string, which a test can
    assert on and a log can be grepped for.

    Lives here, with the registry it reads from, rather than in `authentication`:
    it answers "what may this user do", which is an access-rights question, and
    the authentication app only freezes the answer into a token.
    """
    scopes = set()
    for role in user.roles.all():
        scopes |= set(role.permissions or [])
    return sorted(scopes)
