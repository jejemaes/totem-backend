"""What the controller of a document settled by payments composes.

The routes of the payments of one document, nested under it:

    GET    <prefix>{id}/payments/                list the payments of the document
    POST   <prefix>{id}/payments/                register a payment of the document
    PATCH  <prefix>{id}/payments/{payment_id}/   change one of its payments
    DELETE <prefix>{id}/payments/{payment_id}/   cancel one of its payments

Its `done` payments only; see `PaymentTargetServiceMixin`.

Served by the `PaymentTargetServiceMixin` the document's service composes.
"""

import typing as t
from types import FunctionType

import pydantic
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest
from ninja import Body, Path, Schema
from ninja.errors import HttpError
from ninja.signature.utils import get_path_param_names
from ulid import ULID

from core.api.permission import check_permissions
from core.schemas.utils import _unwrap_list_schema, extract_orm_fields_from_specs, extract_orm_fields_map
from core.services import ServiceValidationMultiError
from payment.models import Payment
from payment.services.mixins import PaymentTargetServiceMixin
from user.security import TokenHasScopePermission


class PaymentTargetModelControllerMixin:
    """The payments of a document, routed under it.

    Declare:
    - `payment_create_request_schema` / `payment_update_request_schema`: the
      bodies, the payment fields without the target ones, which the route forces;
    - `payment_response_schema`: what a payment of the document reads as;
    - `permission_map["payment_read"]`: the scopes of the list, typically the
      document's `read` ones;
    - `permission_map["payment"]`: the scopes of the three writes, typically the
      document's `update` ones.
    Both required: a missing key would mean no scope at all.

    Put it *before* `ModelController` in the bases, as
    `ResequenceModelControllerMixin`: after it, `BaseController.add_routes_to`,
    which does not chain, would never register the routes. The routes are
    registered here rather than declared with `@route` in this body: a routed
    function of a mixin is shared by every controller composing it, see
    `BaseController.add_routes_to`.
    """

    payment_create_request_schema: t.ClassVar[t.Type[Schema]] = None
    payment_update_request_schema: t.ClassVar[t.Type[Schema]] = None
    payment_response_schema: t.ClassVar[t.Type[Schema]] = None

    @classmethod
    def add_routes_to(cls, router) -> None:
        if cls.model:
            if not issubclass(cls.service, PaymentTargetServiceMixin):
                raise ImproperlyConfigured(
                    f"{cls.__name__} inherits PaymentTargetModelControllerMixin, but "
                    f"{cls.service.__name__} does not compose PaymentTargetServiceMixin."
                )
            missing = [
                name for name in (
                    "payment_create_request_schema", "payment_update_request_schema", "payment_response_schema",
                )
                if getattr(cls, name) is None
            ]
            if missing:
                raise ImproperlyConfigured(f"{cls.__name__} declares no {', '.join(missing)}.")
            if get_path_param_names(cls.path_prefix):
                raise ImproperlyConfigured(
                    f"{cls.__name__}: the payment routes do not support a nested path prefix."
                )

            name = cls.model._meta.verbose_name
            decorators = cls._payment_function_decorators()
            cls.method_to_route_function(
                view_func=cls.payment_list,
                path="/{id}/payments/",
                methods=["GET"],
                response=t.List[cls.payment_response_schema],
                operation_id=f"{name.lower()}PaymentList",
                summary=f"List the Payments of {name.capitalize()}",
                decorators=cls._payment_read_function_decorators(),
                view_wrapper=cls._annotate_payment_list_view_function,
                tags=[name],
            )
            cls.method_to_route_function(
                view_func=cls.payment_register,
                path="/{id}/payments/",
                methods=["POST"],
                response={201: cls.payment_response_schema},
                operation_id=f"{name.lower()}PaymentRegister",
                summary=f"Register a Payment of {name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_payment_register_view_function,
                tags=[name],
            )
            cls.method_to_route_function(
                view_func=cls.payment_update,
                path="/{id}/payments/{payment_id}/",
                methods=["PATCH"],
                response=cls.payment_response_schema,
                operation_id=f"{name.lower()}PaymentUpdate",
                summary=f"Update a Payment of {name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_payment_update_view_function,
                tags=[name],
            )
            cls.method_to_route_function(
                view_func=cls.payment_cancel,
                path="/{id}/payments/{payment_id}/",
                methods=["DELETE"],
                response={204: None},
                operation_id=f"{name.lower()}PaymentCancel",
                summary=f"Cancel a Payment of {name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_payment_cancel_view_function,
                tags=[name],
            )

        super().add_routes_to(router)

    @classmethod
    def _payment_function_decorators(cls):
        return cls._payment_scope_decorators("payment")

    @classmethod
    def _payment_read_function_decorators(cls):
        return cls._payment_scope_decorators("payment_read")

    @classmethod
    def _payment_scope_decorators(cls, action):
        permissions = cls._get_action_permissions(action)
        if not permissions:
            raise ImproperlyConfigured(
                f"{cls.__name__} registers the payment routes but its permission_map has no "
                f"{action!r} scopes: they would require none."
            )
        return [check_permissions([TokenHasScopePermission(permissions)])]

    # Annotations

    @classmethod
    def _payment_path_schema(cls, with_payment):
        fields = {"id": (cls._pk_type(), ...)}
        if with_payment:
            fields["payment_id"] = (ULID, ...)
        suffix = "PaymentPathParameters" if with_payment else "PaymentsPathParameters"
        return pydantic.create_model(f"{cls.model.__name__}{suffix}", **fields)

    @classmethod
    def _annotate_payment_list_view_function(cls, view_func, path):
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[cls._payment_path_schema(False), Path()]
        return view_func

    @classmethod
    def _annotate_payment_register_view_function(cls, view_func, path):
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[cls._payment_path_schema(False), Path()]
        annotations["request_body"] = t.Annotated[cls.payment_create_request_schema, Body()]
        return view_func

    @classmethod
    def _annotate_payment_update_view_function(cls, view_func, path):
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[cls._payment_path_schema(True), Path()]
        annotations["request_body"] = t.Annotated[cls.payment_update_request_schema, Body()]
        return view_func

    @classmethod
    def _annotate_payment_cancel_view_function(cls, view_func, path):
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[cls._payment_path_schema(True), Path()]
        return view_func

    # Views

    async def payment_list(self, request: HttpRequest, path_parameters):
        """Not paginated: the payments of one document are a handful."""
        service = request.env.get(self.service)
        try:
            queryset = await service.payment_read(path_parameters.id, fields=self._payment_response_fields())
        except self.model.DoesNotExist:
            raise self._payment_not_found(self.model)
        return [payment async for payment in queryset]

    async def payment_register(self, request: HttpRequest, path_parameters, request_body):
        service = request.env.get(self.service)
        try:
            payment = await service.payment_register(path_parameters.id, request_body)
        except self.model.DoesNotExist:
            raise self._payment_not_found(self.model)
        except ServiceValidationMultiError as exc:
            raise self.service_validation_error_to_api_error(exc, None, loc_path=["body", "request_body"])
        # Refetched, as a creation: the response reads what the database derives.
        return 201, await self._payment_response(request, Payment.objects.filter(pk=payment.pk))

    async def payment_update(self, request: HttpRequest, path_parameters, request_body):
        service = request.env.get(self.service)
        try:
            count, queryset = await service.payment_update(
                path_parameters.id, path_parameters.payment_id, request_body
            )
        except self.model.DoesNotExist:
            raise self._payment_not_found(self.model)
        except ServiceValidationMultiError as exc:
            raise self.service_validation_error_to_api_error(exc, None, loc_path=["body", "request_body"])
        if count == 0:
            raise self._payment_not_found(Payment)
        return await self._payment_response(request, queryset)

    async def payment_cancel(self, request: HttpRequest, path_parameters):
        service = request.env.get(self.service)
        try:
            count = await service.payment_cancel(path_parameters.id, path_parameters.payment_id)
        except self.model.DoesNotExist:
            raise self._payment_not_found(self.model)
        except ServiceValidationMultiError as exc:
            # As the generic delete: the record itself refuses, named by the path.
            raise self.service_validation_error_to_api_error(exc, loc_path=["path", "path_parameters"])
        if count == 0:
            raise self._payment_not_found(Payment)
        return 204, None

    # Utils

    async def _payment_response(self, request, queryset):
        """The payment, loaded with what `payment_response_schema` reads."""
        return await request.env[Payment].apply_query_fields(queryset, self._payment_response_fields()).afirst()

    @classmethod
    def _payment_response_fields(cls):
        """What `payment_response_schema` reads: ninja serializes outside of any
        `sync_to_async`, see `_response_orm_fields`, which reads the controller's
        own model and cannot serve here."""
        orm_field_map = extract_orm_fields_map(_unwrap_list_schema(cls.payment_response_schema), Payment)
        return extract_orm_fields_from_specs(orm_field_map, list(orm_field_map))

    @staticmethod
    def _payment_not_found(model):
        return HttpError(status_code=404, message=f"{model._meta.verbose_name.capitalize()} not found.")
