from core.services import ModelService
from user.models import User, UserRole


class UserService(ModelService):
    model =  User


    # def validate_data(self, data, instance):
    #     raise self.ValidationError({"field": "validation error"})



class UserRoleService(ModelService):
    model =  UserRole
