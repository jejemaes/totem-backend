from typing import List

from ninja import FilterSchema, Schema

from authentication.authenticators import ApiKeyAuth, JWTAuth
from core.api import GroupByModelControllerMixin, ModelController
from payment.schemas import PaymentCreateSchema, PaymentFilterSchema, PaymentSchema, PaymentUpdateSchema
from payment.services import PaymentService
from totem.api import api_v1
from user.security import TokenHasScopePermissionModelControllerMixin


class PaymentController(
    TokenHasScopePermissionModelControllerMixin,
    GroupByModelControllerMixin,
    ModelController,
):
    """Every payment, whatever it settles, under the scopes of `payment`.

    A second way in beside the routes of a document
    (`PaymentTargetModelControllerMixin`), which hold the document's scopes and
    its `done` payments only: here any state, and a payment settling no
    document. The rules are the same either way -- those of `PaymentService`,
    and of the document's service when the payment settles one -- so a payment
    of an invoice written here still obeys the invoice.
    """

    api = api_v1
    service = PaymentService

    path_prefix = "/payment/payments/"
    auth = [JWTAuth(), ApiKeyAuth()]
    permission_map = {
        "read": ["totem.payment.read"],
        "create": ["totem.payment.create"],
        "update": ["totem.payment.update"],
        "delete": ["totem.payment.delete"],
        "group_by": ["totem.payment.read"],
    }

    list_response_schema: Schema = List[PaymentSchema]
    list_filter_schema: FilterSchema = PaymentFilterSchema
    list_ordering_fields = ["date", "amount", "state", "reference", "done_date", "create_date"]
    list_ordering_default_fields = ["-date"]

    retrieve_response_schema: Schema = PaymentSchema
    create_request_schema = PaymentCreateSchema
    create_response_schema = PaymentSchema
    update_request_schema = PaymentUpdateSchema
    update_response_schema = PaymentSchema
