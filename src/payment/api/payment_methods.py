from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import DisplayNameModelControllerMixin, ModelController, ResequenceModelControllerMixin
from payment.schemas import (
    PaymentMethodCreateSchema,
    PaymentMethodDisplayNameSchema,
    PaymentMethodFilterSchema,
    PaymentMethodSchema,
    PaymentMethodUpdateSchema,
)
from payment.services import PaymentMethodService
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin


class PaymentMethodController(
    TokenHasScopePermissionModelControllerMixin,
    DisplayNameModelControllerMixin,
    ResequenceModelControllerMixin,
    ModelController,
):
    api = api_v1
    service = PaymentMethodService

    path_prefix = "/payment/methods/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.paymentmethod.read"],
        "create": ["totem.paymentmethod.create"],
        "update": ["totem.paymentmethod.update"],
        "delete": ["totem.paymentmethod.delete"],
        "display_name": ["totem.paymentmethod.read"],
        "resequence": ["totem.paymentmethod.update"],
    }

    list_response_schema: Schema = List[PaymentMethodSchema]
    list_filter_schema: FilterSchema = PaymentMethodFilterSchema
    list_ordering_fields = ["sequence", "code", "name", "type"]
    list_ordering_default_fields = ["sequence", "code"]

    retrieve_response_schema: Schema = PaymentMethodSchema
    create_request_schema = PaymentMethodCreateSchema
    create_response_schema = PaymentMethodSchema
    update_request_schema = PaymentMethodUpdateSchema
    update_response_schema = PaymentMethodSchema
    display_name_response_schema = PaymentMethodDisplayNameSchema
