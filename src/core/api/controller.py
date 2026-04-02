import inspect
import typing as t
from contextlib import contextmanager
from types import FunctionType

import pydantic
from django.core.exceptions import PermissionDenied
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from ninja import Body, FilterSchema, NinjaAPI, Path, Query, Router, Schema
from ninja.errors import ValidationError, HttpError
from ninja.security.base import AuthBase
from ninja.signature.utils import get_path_param_names
from ninja.utils import normalize_path
from pydantic import BaseModel

from core.schemas.utils import schema_to_orm_fields
from core.services import (
    ServiceEnvironment,
    ServiceContext,
    ServiceValidationMultiError,
)

from .ordering import Ordering, OrderingBase, ordering
from .pagination import PageNumberPagination, PaginationBase, paginate
from .query_fields import QueryField, QueryFieldBase, query_field
from .route import MAGIC_ROUTE_ATTR, Route  # pragma: no cover


class BaseController:

    # `api` a reference to NinjaAPI
    api: t.Optional[NinjaAPI] = None
    _router: t.Optional[Router] = None

    # Singleton pattern
    _instance = None

    # Customizable options
    path_prefix: str = "/"
    auth: t.List[AuthBase] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._request = None
        self._service_env = None
        super().__init__()

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        # Each controller class must have its own router.
        cls._router = Router(auth=cls.auth)

        # Add method decorated as route to the router
        if cls._router is not None:
            cls.add_routes_to(cls._router)

        # Add the router to the API
        if cls.api is not None:
            cls.api.add_router(cls.path_prefix, cls._router)

    @classmethod
    def add_routes_to(cls, router: Router) -> None:
        """
        Automatically registers all route defined as class attributes with the
        controller router.

        This method iterates over all class attributes and registers any that are
        instances have the magic attribute `MAGIC_ROUTE_ATTR` and add them to the
        router.
        """
        view_members = {
            name: member
            for name, member in inspect.getmembers(cls)
            if hasattr(member, MAGIC_ROUTE_ATTR)
        }

        ordered_view_members = sorted(
            view_members.items(),
            key=lambda view_member: list(cls.__dict__).index(view_member[0]),
        )
        for name, func in ordered_view_members:
            route = getattr(func, MAGIC_ROUTE_ATTR, None)
            route.set_controller(cls())  # singleton instance is bind to route
            router.add_api_operation(**route.as_operation())

    def permission_denied(self, message=None):
        if not message:
            message = "You are not allowed to archived this operation."
        raise PermissionDenied(message)

    def request_to_service_context(self, request: HttpRequest) -> ServiceContext:
        user = None  # force none instead of Anonymous user
        if request is not None:
            if request.auth and hasattr(request.auth, "user"):
                user = request.auth.user
        return ServiceContext(user=user)

    @contextmanager
    def with_service_request(
        self,
        request: HttpRequest,
    ):
        old_services_env = self._service_env
        self._service_env = ServiceEnvironment(self.request_to_service_context(request))
        try:
            yield self
        finally:
            if self._service_env is not None:
                self._service_env.__exit__(None, None, None)
                self._service_env = old_services_env

    @property
    def services(self):
        if self._service_env is None:
            raise RuntimeError(
                "Service environment is not set. Use with_service_request context manager."
            )
        return self._service_env.__enter__()


class BaseModelController(BaseController):

    model: Model = None
    path_model = None
    service_name: str = None

    # Route Helpers

    @classmethod
    def method_to_route_function(
        cls,
        view_func: t.Callable,
        path: str,
        methods: t.List[str],
        response: Schema,
        operation_id: str = None,
        summary: str = None,
        description: str = None,
        decorators: t.List[t.Callable] = None,
        view_wrapper: t.Callable = None,
        exclude_unset: bool = False,
        tags: t.Optional[t.List[str]] = None,
    ):
        """This method decorates the given function with the route obj. This is required for the
        method to be added to the API.
        Note: giving a wrapper will bind the wrapped function to the current class.
        """
        if view_wrapper:
            # Use this wrapper to add annotation on the view function (method)
            view_func = view_wrapper(view_func, path)

            # Rebind the wrapped method (annotated) on the controller class, to replace the original method.
            setattr(cls, view_func.__name__, view_func)

        route = Route(
            view_func=view_func,
            path=path,
            methods=methods,
            response=response,
            operation_id=operation_id,
            summary=summary,
            description=description,
            decorators=decorators,
            exclude_unset=exclude_unset,
            tags=tags,
        )
        route.set_controller(cls())
        setattr(view_func, MAGIC_ROUTE_ATTR, route)

    @classmethod
    def _get_default_path_schema(cls, path, view_func):
        path = normalize_path(cls.path_prefix + path)
        path_params = get_path_param_names(path)
        func_params = t.get_type_hints(view_func)

        if path_params and cls.path_model is not None:
            return cls.path_model

        schema_fields = {}
        for param in path_params:
            schema_fields[param] = func_params.get(param, str)

        return pydantic.create_model("PathParameters", **schema_fields)

    # Error Handling

    def service_validation_error_to_api_error(
        self,
        exc: ServiceValidationMultiError,
        response_schema: BaseModel,
        loc_path: t.List[str] = ["body", "request_body"],
    ) -> ValidationError:
        """Convert a ServiceValidationMultiError to a Ninja ValidationError, with error location mapped to the response schema fields."""
        fields_map = schema_to_orm_fields(response_schema, self.model)

        result = []
        for key, error_dict in exc.dict().items():
            for field, messages in error_dict.items():
                result.append(
                    {
                        "type": "validation_error",
                        "loc": loc_path + [fields_map.get(field, field)],
                        "msg": ".".join(messages),
                        "ctx": {
                            "key": key,
                        },
                    }
                )
        return ValidationError(result)


# -------------------------------------------
# Model Mixin (CRUD Operations)
# -------------------------------------------


class ListModelControllerMixin:

    list_response_schema: Schema = None
    list_filter_schema: FilterSchema = None
    list_ordering: t.Optional[t.Type[OrderingBase]] = Ordering
    list_ordering_fields: t.List[str] = []
    list_ordering_default_fields: t.List[str] = []
    list_ordering_fields_alias: t.Dict[str, str] = {}
    list_pagination: t.Optional[t.Type[PaginationBase]] = PageNumberPagination
    list_query_field_class: t.Optional[t.Type[QueryFieldBase]] = QueryField

    @classmethod
    def add_routes_to(cls, router) -> None:
        if cls.model and cls.list_response_schema:
            decorators = cls._list_function_decorators()

            cls.method_to_route_function(
                view_func=cls.list,
                path="/",
                methods=["GET"],
                response=cls.list_response_schema,
                operation_id=f"{cls.model._meta.verbose_name.lower()}List",
                summary=f"List {cls.model._meta.verbose_name_plural.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_list_view_function,
                tags=[cls.model._meta.verbose_name],
                exclude_unset=True,
            )

        super().add_routes_to(router)

    @classmethod
    def _list_function_decorators(cls):
        decorators = []
        if cls.list_pagination is not None:
            decorators.append(paginate(cls.list_pagination))
        if cls.list_response_schema is not None:
            decorators.append(
                query_field(
                    cls.list_query_field_class,
                    field_map=schema_to_orm_fields(cls.list_response_schema, cls.model),
                    pass_parameter="query_fields",
                )
            )
        if cls.list_ordering is not None:
            decorators.append(
                ordering(
                    cls.list_ordering,
                    field_map=cls.get_ordering_fields_map(),
                    default_ordering_fields=cls.list_ordering_default_fields,
                    pass_parameter="ordering_fields",
                    execute_ordering=False,  # disable automatic ordering execution to let the controller handle it in the list method
                )
            )
        return decorators

    @classmethod
    def get_ordering_fields_map(cls):
        response_schema_field_map = schema_to_orm_fields(
            cls.list_response_schema, cls.model
        )
        field_map = {}
        for fname in cls.list_ordering_fields:
            alias = None
            if fname in cls.list_ordering_fields_alias:
                alias = cls.list_ordering_fields_alias[fname]
            elif fname in response_schema_field_map:
                alias = response_schema_field_map[fname]
            else:
                alias = fname  # supposed the ordering alias has the same name as the django model one
            field_map[fname] = alias
        return field_map

    @classmethod
    def _annotate_list_view_function(
        cls, view_func: t.Callable[..., t.Any], path: str
    ) -> t.Callable[..., t.Any]:
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        if cls.list_filter_schema:
            annotations["query_parameters"] = t.Annotated[
                cls.list_filter_schema, Query(default=None, include_in_schema=False)
            ]
        return view_func

    def list(
        self,
        request,
        path_parameters: t.Optional[BaseModel],
        query_parameters: t.Optional[FilterSchema],
        **kwargs: t.Any,
    ) -> QuerySet:
        # TODO : handle path_parameters
        ordering_fields = None
        ordering_parameters = kwargs.pop("ordering_fields", None)
        if ordering_parameters:
            ordering_fields = ordering_parameters.ordering
        return self.services[self.service_name].read(
            query_parameters, ordering=ordering_fields
        )


class RetrieveModelControllerMixin:

    retrieve_response_schema: Schema = None

    @classmethod
    def add_routes_to(cls, router) -> None:
        if cls.model and cls.retrieve_response_schema:
            decorators = cls._retrieve_function_decorators()

            cls.method_to_route_function(
                view_func=cls.retrieve,
                path="/{id}/",
                methods=["GET"],
                response=cls.retrieve_response_schema,
                operation_id=f"{cls.model._meta.verbose_name.lower()}Retrieve",
                summary=f"Retrieve {cls.model._meta.verbose_name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_retrieve_view_function,
                tags=[cls.model._meta.verbose_name],
            )

        super().add_routes_to(router)

    @classmethod
    def _retrieve_function_decorators(cls):
        return []

    @classmethod
    def _annotate_retrieve_view_function(
        cls, view_func: t.Callable[..., t.Any], path: str
    ) -> t.Callable[..., t.Any]:
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        return view_func

    def retrieve(
        self,
        request: HttpRequest,
        path_parameters: t.Optional[BaseModel],
    ) -> Model:
        queryset = self.services[self.service_name].read()
        try:
            return queryset.get(
                **(path_parameters.model_dump() if path_parameters else {})
            )
        except queryset.model.DoesNotExist as exc:
            raise HttpError(
                status_code=404,
                message=f"{self.model._meta.verbose_name.capitalize()} not found.",
            ) from exc


class CreateModelControllerMixin:

    create_request_schema: Schema = None
    create_response_schema: Schema = None

    @classmethod
    def add_routes_to(cls, router) -> None:
        if cls.model and cls.create_request_schema:
            decorators = cls._create_function_decorators()

            cls.method_to_route_function(
                view_func=cls.create,
                path="/",
                methods=["POST"],
                response={201: cls.create_response_schema},
                operation_id=f"{cls.model._meta.verbose_name.lower()}Create",
                summary=f"Create {cls.model._meta.verbose_name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_create_view_function,
                tags=[cls.model._meta.verbose_name],
            )

        super().add_routes_to(router)

    @classmethod
    def _create_function_decorators(cls):
        return []

    @classmethod
    def _annotate_create_view_function(
        cls, view_func: t.Callable[..., t.Any], path: str
    ) -> t.Callable[..., t.Any]:
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        annotations["request_body"] = t.Annotated[cls.create_request_schema, Body()]
        return view_func

    def create(
        self,
        request: HttpRequest,
        path_parameters: t.Optional[BaseModel],
        request_body: BaseModel,
    ) -> Model:
        try:
            instances = self.services[self.service_name].create([request_body])
            return instances[0] if instances else None
        except ServiceValidationMultiError as exc:
            raise self.service_validation_error_to_api_error(
                exc, self.create_response_schema, loc_path=["body", "request_body"]
            )


class UpdateModelControllerMixin:

    update_request_schema: Schema = None
    update_response_schema: Schema = None

    @classmethod
    def add_routes_to(cls, router) -> None:
        if cls.model and cls.update_request_schema:
            decorators = cls._update_function_decorators()

            cls.method_to_route_function(
                view_func=cls.update,
                path="/{id}/",
                methods=["PATCH"],
                response=cls.update_response_schema,
                operation_id=f"{cls.model._meta.verbose_name.lower()}Update",
                summary=f"Update {cls.model._meta.verbose_name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_update_view_function,
                tags=[cls.model._meta.verbose_name],
            )

        super().add_routes_to(router)

    @classmethod
    def _update_function_decorators(cls):
        return []

    @classmethod
    def _annotate_update_view_function(
        cls, view_func: t.Callable[..., t.Any], path: str
    ) -> t.Callable[..., t.Any]:
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        annotations["request_body"] = t.Annotated[cls.update_request_schema, Body()]
        return view_func

    def update(
        self,
        request: HttpRequest,
        path_parameters: t.Optional[BaseModel],
        request_body: BaseModel,
    ) -> Model:
        try:
            filters = path_parameters.model_dump() if path_parameters else {}
            count, queryset = self.services[self.service_name].update(
                filters, request_body
            )
            if count == 0:
                raise HttpError(
                    status_code=404,
                    message=f"{self.model._meta.verbose_name.capitalize()} not found.",
                )
            return queryset.first() if count > 0 else None
        except ServiceValidationMultiError as exc:
            raise self.service_validation_error_to_api_error(
                exc, self.create_response_schema, loc_path=["body", "request_body"]
            )


class DeleteModelControllerMixin:

    @classmethod
    def add_routes_to(cls, router) -> None:
        if cls.model:
            decorators = cls._delete_function_decorators()

            cls.method_to_route_function(
                view_func=cls.delete,
                path="/{id}/",
                methods=["DELETE"],
                response={204: None},
                operation_id=f"{cls.model._meta.verbose_name.lower()}Delete",
                summary=f"Delete {cls.model._meta.verbose_name.capitalize()}",
                decorators=decorators,
                view_wrapper=cls._annotate_delete_view_function,
                tags=[cls.model._meta.verbose_name],
            )

        super().add_routes_to(router)

    @classmethod
    def _delete_function_decorators(cls):
        return []

    @classmethod
    def _annotate_delete_view_function(
        cls, view_func: t.Callable[..., t.Any], path: str
    ) -> t.Callable[..., t.Any]:
        annotations = t.cast(FunctionType, view_func).__annotations__
        annotations["path_parameters"] = t.Annotated[
            cls._get_default_path_schema(path, view_func),
            Path(default=None, include_in_schema=False),
        ]
        return view_func

    def delete(
        self,
        request: HttpRequest,
        path_parameters: t.Optional[BaseModel],
    ) -> None:
        filters = path_parameters.model_dump() if path_parameters else {}
        count = self.services[self.service_name].delete(filters)
        if count == 0:
            raise HttpError(
                status_code=404,
                message=f"{self.model._meta.verbose_name.capitalize()} not found.",
            )


class ModelController(
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
    CreateModelControllerMixin,
    UpdateModelControllerMixin,
    DeleteModelControllerMixin,
    BaseModelController,
):
    pass
