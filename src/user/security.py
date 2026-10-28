from django.core.exceptions import ImproperlyConfigured
from django.db.models import Model, Q

from core.api.permission import BasePermission, check_permissions
from user.access_policy import BaseRule
from user.access_rights import register_permission
from user.models import User

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.user.create", "Create Users", is_public=True)
register_permission("totem.user.read", "Read Users", is_public=True)
register_permission("totem.user.update", "Update Users", is_public=True)
register_permission("totem.user.delete", "Delete Users", is_public=True)

register_permission("totem.userrole.read", "Read User Roles", is_public=True)

# ---------------------------------------------------------
# Permissions
# ---------------------------------------------------------


class IsAuthenticated(BasePermission):
    """ A *user* is acting, not merely a credential.

    Guards `request.auth` itself now that a machine caller exists: an `ApiKey`
    lands in `request.auth` with `user` at `None`, so this returns False and the
    route answers 403. That is the intended answer -- `/users/me/` has no profile
    to return to a key -- and the guard is what keeps it a 403 instead of an
    `AttributeError`.
    """

    def has_permission(self, request):
        auth = request.auth
        return bool(auth and auth.user and auth.user.is_authenticated)


class TokenHasScopePermission(BasePermission):

    def __init__(self, required_scopes):
        super().__init__()
        if not isinstance(required_scopes, list):
            required_scopes = [required_scopes]
        self.scopes = required_scopes

    def has_permission(self, request) -> bool:
        if request.auth:
            # `has_scopes`, from `ScopedPrincipalMixin`, is what both
            # authenticators share. Same semantics as the `is_valid` it replaces,
            # minus its expiry half: expiry is already proven by the signature
            # check (JWT) or by the `usable()` filter (API key) before
            # `request.auth` exists at all.
            return request.auth.has_scopes(self.scopes)
        return False


# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------


class UserManageOwnProfileRule(BaseRule):
    identifier: str = "user_manage_own_profile"
    model: Model = User
    name: str = "Manage My Own User Profile"
    description: str = "Read and edit your Current User Profile."
    operations = ["read", "update"]

    def scope_filter(self, context) -> Q:
        if context.user:
            return Q(pk=context.user.pk)
        return Q()


class UserManageAllUserRule(BaseRule):
    identifier: str = "user_manage_all_user"
    model: Model = User
    name: str = "Manage All User Profile"
    description: str = "Create, read, edit and delete All User Profile."
    operations = ["read", "create", "update", "delete"]

    def scope_filter(self, context) -> Q:
        return ~Q(pk__in=[])  # always true


# ---------------------------------------------------------
# Controller Mixin
# (Only for CRUD operations)
# ---------------------------------------------------------


class TokenHasScopePermissionModelControllerMixin:

    permission_map = {}

    @classmethod
    def _list_function_decorators(cls):
        decorators = super()._list_function_decorators()
        permissions = cls._get_action_permissions("read")
        if permissions:
            decorators.append(check_permissions([TokenHasScopePermission(permissions)]))
        return decorators

    @classmethod
    def _retrieve_function_decorators(cls):
        decorators = super()._retrieve_function_decorators()
        permissions = cls._get_action_permissions("read")
        if permissions:
            decorators.append(check_permissions([TokenHasScopePermission(permissions)]))
        return decorators

    @classmethod
    def _create_function_decorators(cls):
        decorators = super()._create_function_decorators()
        permissions = cls._get_action_permissions("create")
        if permissions:
            decorators.append(check_permissions([TokenHasScopePermission(permissions)]))
        return decorators

    @classmethod
    def _update_function_decorators(cls):
        decorators = super()._update_function_decorators()
        permissions = cls._get_action_permissions("update")
        if permissions:
            decorators.append(check_permissions([TokenHasScopePermission(permissions)]))
        return decorators

    @classmethod
    def _delete_function_decorators(cls):
        decorators = super()._delete_function_decorators()
        permissions = cls._get_action_permissions("delete")
        if permissions:
            decorators.append(check_permissions([TokenHasScopePermission(permissions)]))
        return decorators

    @classmethod
    def _resequence_function_decorators(cls):
        # Required rather than defaulted: a key missing from `permission_map` means
        # no scope at all, the trap `DELETE` already sets for `ModelController`.
        if not cls._get_action_permissions("resequence"):
            raise ImproperlyConfigured(
                f"{cls.__name__} registers /resequence/ but its permission_map has no "
                f"'resequence' scopes: the route would require none."
            )
        decorators = super()._resequence_function_decorators()
        decorators.append(
            check_permissions([TokenHasScopePermission(cls._get_action_permissions("resequence"))])
        )
        return decorators

    @classmethod
    def _display_name_function_decorators(cls):
        # Required, as for `resequence`: a missing key would mean no scope at all.
        if not cls._get_action_permissions("display_name"):
            raise ImproperlyConfigured(
                f"{cls.__name__} registers /display-name/ but its permission_map has no "
                f"'display_name' scopes: the route would require none."
            )
        decorators = super()._display_name_function_decorators()
        decorators.append(
            check_permissions([TokenHasScopePermission(cls._get_action_permissions("display_name"))])
        )
        return decorators

    @classmethod
    def _group_by_function_decorators(cls):
        # Required, as for `resequence`: a missing key would mean no scope at all.
        # Its own key rather than `read`'s, though it is a read: the route is opt-in,
        # and so is saying which scopes reach it.
        if not cls._get_action_permissions("group_by"):
            raise ImproperlyConfigured(
                f"{cls.__name__} registers /group-by/ but its permission_map has no "
                f"'group_by' scopes: the route would require none."
            )
        decorators = super()._group_by_function_decorators()
        decorators.append(
            check_permissions([TokenHasScopePermission(cls._get_action_permissions("group_by"))])
        )
        return decorators

    @classmethod
    def _get_action_permissions(cls, action):
        permission_map = getattr(cls, "permission_map", {})
        return permission_map.get(action, [])
