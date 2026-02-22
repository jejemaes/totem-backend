import inspect
import typing as t
from contextlib import contextmanager
from types import FunctionType

import pydantic
from asgiref.sync import async_to_sync
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import ManyToManyField, Model, QuerySet
from django.db.utils import DatabaseError
from django.http import HttpRequest
from ninja import Body, FilterSchema, NinjaAPI, Path, Query, Router, Schema
from ninja.errors import ValidationError
from ninja.security.base import AuthBase
from ninja.signature.utils import get_path_param_names
from ninja.utils import normalize_path
from pydantic import BaseModel

from core.schemas.utils import extract_orm_fields_map
from user.access_policy import apply_access_rules, request_to_context

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
        self.action = None
        self.request = None
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

    @contextmanager
    def set_context(
        self,
        request: HttpRequest,
        action: str,
    ):
        old_action = self.action
        old_request = self.request
        self.action = action
        self.request = request
        try:
            yield
        finally:
            self.action = old_action
            self.request = old_request

    def permission_denied(self, message=None):
        if not message:
            message = "You are not allowed to archived this operation."
        raise PermissionDenied(message)


class BaseModelController(BaseController):

    model: Model = None
    path_model = None

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

    # Queryset Helpers

    def get_queryset(self):
        return self.model._default_manager.all()

    def apply_query_parameters(
        self, queryset: QuerySet[Model], query_parameters: BaseModel
    ):
        if isinstance(query_parameters, FilterSchema):
            queryset = query_parameters.filter(queryset)
        elif isinstance(query_parameters, BaseModel):
            queryset = queryset.filter(
                **query_parameters.model_dump(exclude_unset=True)
            )
        return queryset

    def apply_path_parameters(
        self, queryset: QuerySet[Model], path_parameters: BaseModel
    ):
        return queryset.get(**(path_parameters.model_dump() if path_parameters else {}))

    # Access rules

    def apply_access_rules(self, queryset: QuerySet, operation: str):
        context = async_to_sync(request_to_context)(self.request)
        return async_to_sync(apply_access_rules)(queryset, operation, context)

    # Data Validation

    def validate_data(self, request_body: BaseModel, instance: Model = None):
        """
        :param request:body: model instance of pydantic schema. This is already validate (done during instanciation). Values are python obj.
        :param instance: the django model instance to validate the data against if given. None in case of creation.

        Note: don't use `model_dump` as it will serialize m2m relations (`core.schemas.QuerySet`) into a list of pk scalar type.
        """
        if instance:
            fields = request_body.model_fields_set
        else:
            fields = set(request_body.model_fields)

        # TODO: maybe use alias ?
        values = {}
        for fname in fields:
            values[fname] = getattr(request_body, fname, None)
        return values


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
        if cls.list_pagination:
            decorators.append(paginate(cls.list_pagination))
        if cls.list_response_schema:
            decorators.append(
                query_field(
                    cls.list_query_field_class,
                    field_map=cls._get_list_response_fields_map(),
                    pass_parameter="query_fields",
                )
            )
        if cls.list_ordering:
            decorators.append(
                ordering(
                    cls.list_ordering,
                    field_map=cls.get_ordering_fields_map(),
                    default_ordering_fields=cls.list_ordering_default_fields,
                    pass_parameter="ordering_fields",
                )
            )
        return decorators

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
        queryset = self.get_queryset()
        queryset = self.apply_query_parameters(queryset, query_parameters)
        return self.apply_access_rules(queryset, "read")

    _list_response_fields_map: t.Dict[str, str] = None

    @classmethod
    def _get_list_response_fields_map(cls):
        """Get the dict mapping pydantic schema field name with the corresponding django model field name,
        based on the `list_response_schema`.
        :returns: dict where key is schema field, and value is the orm field name
        """
        if cls._list_response_fields_map is None:
            if cls.list_response_schema:
                schema = cls.list_response_schema
                if (
                    cls.list_response_schema.__origin__ is list
                    or cls.list_response_schema.__origin__ is t.List
                ):
                    schema = cls.list_response_schema.__args__[0]
                cls._list_response_fields_map = {
                    fname: fspec["source"]
                    for fname, fspec in extract_orm_fields_map(
                        schema, cls.model
                    ).items()
                }
            else:
                cls._list_response_fields_map = {}
        return cls._list_response_fields_map

    @classmethod
    def get_ordering_fields_map(cls):
        response_schema_field_map = cls._get_list_response_fields_map()

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
        queryset = self.get_queryset()
        queryset = self.apply_access_rules(queryset, "read")
        return queryset.get(**(path_parameters.model_dump() if path_parameters else {}))


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
        """Override this method to add additional non-atomic operations."""
        with transaction.atomic():
            queryset = self.get_queryset()

            # Preprocess data
            validated_data = self.validate_data(request_body, instance=None)

            # Remove many-to-many relationships from validated_data.
            # They are not valid arguments to the default `.create()` method,
            # as they require that the instance has already been saved.
            many_to_many = {}
            for field in queryset.model._meta.get_fields():
                if isinstance(field, ManyToManyField) and field.name in validated_data:
                    many_to_many[field.name] = validated_data.pop(field.name)

            # Create instance
            try:
                instance = queryset.create(**validated_data)
            except TypeError as exc:
                raise TypeError(str(exc))
            except DatabaseError as exc:
                raise ValidationError(
                    [str(exc)]
                )  # TODO parse error and respond with violation error define on model constraint

            # Access rules check
            queryset = self.apply_access_rules(queryset, "create")
            if queryset.filter(pk=instance.pk).count() != 1:
                self.permission_denied(
                    "Your access rules prevent you to create this object."
                )

            # Save many-to-many relationships after the instance is created, and set it in the prefetch cache
            if many_to_many:
                prefetched_objects = getattr(instance, "_prefetched_objects_cache", {})
                for field_name, value in many_to_many.items():
                    field = getattr(instance, field_name)
                    # optimization: `set` will cause a read but since we are in a creation,
                    # there is no exsting relations.
                    field.add(*value)
                    # Set in cache in order to avoid refetching the m2m relation when serializing.
                    # This can be done since we are in creation mode. m2m cache value is a django queryset.
                    prefetched_objects[field_name] = value

                setattr(instance, "_prefetched_objects_cache", prefetched_objects)

            # Postprocess
            self._create_postprocess(request, instance)

        return instance

    def _create_postprocess(self, request: HttpRequest, instance: Model):
        """This is part of the atomic process of creation. Any error here will rollback the create.
        Override this method to add additional atomic operation.
        """
        return instance


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
        """Override this method to add additional non-atomic operations."""
        with transaction.atomic():
            queryset = self.get_queryset()
            queryset = self.apply_access_rules(queryset, "update")
            instance = queryset.get(
                **(path_parameters.model_dump() if path_parameters else {})
            )

            # Preprocess data
            validated_data = self.validate_data(request_body, instance=instance)

            # Remove many-to-many relationships from validated_data.
            # They are not valid arguments to the default `.create()` method,
            # as they require that the instance has already been saved.
            many_to_many = {}
            for field in queryset.model._meta.get_fields():
                if isinstance(field, ManyToManyField) and field.name in validated_data:
                    many_to_many[field.name] = validated_data.pop(field.name)

            # Update instance
            try:
                for attr, value in validated_data.items():
                    setattr(instance, attr, value)
                instance.save(update_fields=list(validated_data))
            except DatabaseError as exc:
                raise ValidationError(
                    [str(exc)]
                )  # TODO parse error and respond with violation error define on model constraint

            # Save many-to-many relationships after the instance is created.
            if many_to_many:
                for field_name, value in many_to_many.items():
                    field = getattr(instance, field_name)
                    field.set(value)
                    if not hasattr(instance, "_prefetched_objects_cache"):
                        instance._prefetched_objects_cache = {}
                    # Update cache in order to avoid refetching the m2m relation when serializing.
                    # This can be done since we are in update mode, we just need to update the cache value with the new related objects.
                    instance._prefetched_objects_cache[field_name] = value

            # Postprocess
            self._update_postprocess(request, instance)

            return instance

    def _update_postprocess(self, request: HttpRequest, instance: Model):
        """This is part of the atomic process of update. Any error here will rollback the update.
        Override this method to add additional atomic operation.
        """
        return instance


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
        queryset = self.get_queryset()
        queryset = self.apply_access_rules(queryset, "delete")
        instance = queryset.get(
            **(path_parameters.model_dump() if path_parameters else {})
        )

        instance_pk = instance.pk
        instance.delete()
        self._delete_postprocess(request, instance_pk)

    def _delete_postprocess(self, request: HttpRequest, instance_pk: t.Any):
        """This is part of the atomic process of deletion. Any error here will rollback the delete.
        Override this method to add additional atomic operation.
        """
        return instance_pk


class ModelController(
    ListModelControllerMixin,
    RetrieveModelControllerMixin,
    CreateModelControllerMixin,
    UpdateModelControllerMixin,
    DeleteModelControllerMixin,
    BaseModelController,
):
    pass
