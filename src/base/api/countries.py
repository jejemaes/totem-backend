from typing import List

from ninja import FilterSchema, Schema

from core.api import BaseModelController, ListModelControllerMixin, RetrieveModelControllerMixin
from oauth.authentication import OAuthTokenAuthentication
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin
from base.schemas import CountryFilterSchema, CountryPathParam, CountrySchema
from base.services import CountryService


class CountryController(
    TokenHasScopePermissionModelControllerMixin,
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
    BaseModelController,
):
    api = api_v1
    service = CountryService

    path_prefix = "/countries/"
    path_model = CountryPathParam
    auth = [OAuthTokenAuthentication()]
    permission_map = {
        "read": ["totem.country.read"],
    }

    list_response_schema: Schema = List[CountrySchema]
    list_filter_schema: FilterSchema = CountryFilterSchema
    list_ordering_fields = [
        "name",
        "code",
    ]
    list_ordering_default_fields = ["name"]

    retrieve_response_schema: Schema = CountrySchema
