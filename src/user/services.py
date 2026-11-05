from asgiref.sync import sync_to_async
from django.contrib.auth import password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models

from core.services import (
    CreateMixin,
    DeleteMixin,
    ReadMixin,
    ServiceBase,
    ServiceValidationError,
    ServiceValidationMultiError,
    UpdateMixin,
)
from user.models import User, UserRole
from user.schemas import UserCreateSchema, UserUpdateSchema


class UserService(
    CreateMixin[UserCreateSchema],
    ReadMixin,
    UpdateMixin[UserUpdateSchema],
    DeleteMixin,
    ServiceBase[User],
):
    # def validate_data(self, data, instance):
    #     raise self.ValidationError({"field": "validation error"})

    # Password
    #
    # Not a field of `UserUpdateSchema`: `update` writes values as they come, and a
    # password must be hashed, and validated against `AUTH_PASSWORD_VALIDATORS`
    # with the instance at hand (`UserAttributeSimilarityValidator` compares it to
    # the login and the email). Hence two dedicated operations.
    #
    # Neither revokes the refresh tokens of the user: the sessions already open
    # stay valid until they expire. A deliberate choice, not an oversight.

    async def change_password(self, old_password: str, new_password: str) -> None:
        """Replace the password of the acting user, who must prove the current one.

        Not narrowed by the access rules: whatever their roles allow on other
        users, anybody may change their own password.
        """
        if self.user is None:
            # An API key: there is no "own" password to change.
            raise PermissionDenied("Only a user has a password to change.")
        queryset = self.get_queryset().filter(pk=self.user.pk)
        await sync_to_async(self._write_password, thread_sensitive=True)(
            queryset, new_password, old_password=old_password
        )

    async def set_password(self, pk, new_password: str) -> None:
        """Replace the password of the user `pk`, without the current one.

        Within the `update` rules of the acting user: a user out of reach answers
        `DoesNotExist`, as `update` would, so their existence does not leak.
        """
        scoped_queryset = await self.apply_access_rules(self.get_queryset(), "update")
        await sync_to_async(self._write_password, thread_sensitive=True)(
            scoped_queryset.filter(pk=pk), new_password
        )

    def _write_password(self, queryset: models.QuerySet, new_password: str, old_password=None) -> None:
        """The sync body of both: hashing and validating are synchronous, and
        costly enough on purpose not to run on the event loop."""
        instance = queryset.get()
        error = ServiceValidationError({})
        if old_password is not None and not instance.check_password(old_password):
            error.add_message("The current password is incorrect.", key="old_password")
        try:
            password_validation.validate_password(new_password, user=instance)
        except ValidationError as exc:
            error.add_message(exc.messages, key="new_password")
        if error:
            raise ServiceValidationMultiError({instance.pk: error}, code="password_invalid")

        instance.set_password(new_password)
        # `update`, not `save()`, as every write of a service. Writes no
        # `user_type`, so `UserQuerySet.update` signals no change of rights.
        queryset.update(password=instance.password)


class UserRoleService(ReadMixin, ServiceBase[UserRole]):
    """Read-only: no controller writes roles.

    `browse` still comes from `ServiceBase`, which is what `UserService` needs to
    resolve the `roles` relation.
    """
