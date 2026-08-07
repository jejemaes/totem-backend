from core.services import (
    CreateMixin,
    DeleteMixin,
    ReadMixin,
    ServiceBase,
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
    pass


class UserRoleService(ReadMixin, ServiceBase[UserRole]):
    """Read-only: no controller writes roles.

    `browse` still comes from `ServiceBase`, which is what `UserService` needs to
    resolve the `roles` relation.
    """
