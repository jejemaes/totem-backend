import asyncio
import functools
import inspect
import typing as t

from ninja.constants import NOT_SET, NOT_SET_TYPE
from ninja.signature import is_async
from ninja.throttling import BaseThrottle
from ninja.types import TCallable

from .permission import BasePermission, check_permissions

POST = "POST"
PUT = "PUT"
PATCH = "PATCH"
DELETE = "DELETE"
GET = "GET"
HEAD = "HEAD"
OPTIONS = "OPTIONS"
TRACE = "TRACE"
ROUTE_METHODS = [POST, PUT, PATCH, DELETE, GET, HEAD, OPTIONS, TRACE]


MAGIC_ROUTE_ATTR = "__controller_route__"


class RouteInvalidParameterException(Exception):
    pass


class Route(object):
    """
    Decorates Controller class methods with HTTP Operation methods and as a route function handler

    Example:
        ```python
        from core.api import ControllerBase, route

        class SampleController(ControllerBase):
            @route.post('/create')
            def create_sample():
                pass

            @route.get('/list')
            def get_all_samples():
                pass
        ```
    """

    def __init__(
        self,
        view_func: TCallable,
        *,
        path: str,
        methods: t.List[str],
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
        decorators: t.List[t.Callable] = [],
    ) -> None:
        if not isinstance(methods, list):
            raise RouteInvalidParameterException("methods must be a list")

        methods = [m.upper() for m in methods]
        not_valid_methods = list(set(methods) - set(ROUTE_METHODS))
        if not_valid_methods:
            raise RouteInvalidParameterException(
                f"Method {','.join(not_valid_methods)} not allowed"
            )

        _response = response
        if isinstance(response, list):
            _response_computed = {}
            for item in response:
                if isinstance(item, dict):
                    _response_computed.update(item)
                elif isinstance(item, tuple):
                    _response_computed.update({item[0]: item[1]})
            if not _response_computed:
                raise RouteInvalidParameterException(
                    f"Invalid response configuration: {response}"
                )
            _response = _response_computed

        ninja_route_params = dict(
            path=path,
            methods=methods,
            auth=auth,
            throttle=throttle,
            response=_response,
            operation_id=operation_id,
            summary=summary,
            description=description,
            tags=tags,
            deprecated=deprecated,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            url_name=url_name,
            include_in_schema=include_in_schema,
            openapi_extra=openapi_extra,
        )
        self.route_params = ninja_route_params
        self.is_async = is_async(view_func)
        self.view_func = view_func
        self.name = None
        self._api_controller = None
        # decorators
        self.decorators = decorators or [] # allow to create route without the decorator
        if permissions:
            self.decorators.append(check_permissions(permissions))

    @classmethod
    def _create_route_function(
        cls,
        view_func: TCallable,
        *,
        path: str,
        methods: t.List[str],
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> TCallable:
        if response is NOT_SET:
            type_hint = t.get_type_hints(view_func).get("return") or NOT_SET
            if not isinstance(type_hint, t._SpecialForm):
                response = type_hint
        route_obj = cls(
            view_func,  # type:ignore[arg-type]
            path=path,
            methods=methods,
            auth=auth,
            response=response,
            operation_id=operation_id,
            summary=summary,
            description=description,
            tags=tags,
            deprecated=deprecated,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            url_name=url_name,
            include_in_schema=include_in_schema,
            permissions=permissions,
            openapi_extra=openapi_extra,
            throttle=throttle,
        )

        setattr(view_func, MAGIC_ROUTE_ATTR, route_obj)
        return view_func

    def set_controller(self, controller):
        self._api_controller = controller

    def as_operation(self) -> dict[str, t.Any]:
        return {
            "view_func": functools.reduce(
                lambda f, g: g(f),
                reversed(self.decorators),
                self._create_standalone_handler(self.view_func),
            ),
            **self.route_params,
        }

    def _create_standalone_handler(
        self, view_func: t.Callable[..., t.Any]
    ) -> t.Callable[..., t.Any]:

        @functools.wraps(view_func)
        async def async_handler(*args: t.Any, **kwargs: t.Any) -> t.Any:
            request = args[0] # heuristic
            with self._api_controller.set_context(request, action=view_func.__name__):
                return await view_func(self._api_controller, *args, **kwargs)

        @functools.wraps(view_func)
        def sync_handler(*args: t.Any, **kwargs: t.Any) -> t.Any:
            request = args[0] # heuristic
            with self._api_controller.set_context(request, action=view_func.__name__):
                return view_func(self._api_controller, *args, **kwargs)

        standalone_handler = (
            async_handler if asyncio.iscoroutinefunction(view_func) else sync_handler
        )

        if self.name is not None:
            standalone_handler.__name__ = self.name

        return self._resolve_api_func_signature(standalone_handler)

    def _get_required_api_func_signature(self, view_func) -> t.Tuple:
        skip_parameters = ["self"]
        sig_inspect = inspect.signature(view_func)
        sig_parameter = []
        for parameter in sig_inspect.parameters.values():
            if parameter.name not in skip_parameters:
                sig_parameter.append(parameter)
        return sig_inspect, sig_parameter

    def _resolve_api_func_signature(self, context_func: t.Callable) -> t.Callable:
        """ Override function signature to remove the `self` argument as handler is not a function but a method.
            Adapted from django-ninja-extra (see `route_functions.py`)
        """
        sig_inspect, sig_parameter = self._get_required_api_func_signature(context_func)
        sig_replaced = sig_inspect.replace(parameters=sig_parameter)
        context_func.__signature__ = sig_replaced  # type: ignore
        return context_func

    # Method Handlers

    @classmethod
    def get(
        cls,
        path: str = "",
        *,
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> t.Callable[[TCallable], TCallable]:
        """
        A GET Operation method decorator
         eg.

        ```python
        @route.get()
        def get_operation(self):
        ...
        ```
        :param path: uniques endpoint path string
        :param auth: endpoint authentication method. default: `NOT_SET`
        :param response: `dict[status_code, schema]` or `Schema` used validated returned response. default: `None`
        :param operation_id: unique id that distinguishes `operation` in path view. default: `None`
        :param summary: describes your endpoint. default: `None`
        :param description: other description of your endpoint. default: `None`
        :param tags: list of strings for grouping endpoints only for documentation purpose. default: `None`
        :param deprecated: declares an endpoint deprecated. default: `None`
        :param by_alias: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_unset: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_defaults: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_none: pydantic schema filters applied to `response` schema object. default: `False`
        :param url_name: a name to an endpoint which can be resolved using `reverse` function in django. default: `None`
        :param include_in_schema: indicates whether an endpoint should appear on the swagger documentation
        :param permissions: collection permission classes. default: `None`
        :return: Route[GET]
        """
        def decorator(view_func: TCallable) -> TCallable:
            return cls._create_route_function(
                view_func,
                path=path,
                methods=[GET],
                auth=auth,
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                url_name=url_name,
                include_in_schema=include_in_schema,
                permissions=permissions,
                openapi_extra=openapi_extra,
                throttle=throttle,
            )

        return decorator

    @classmethod
    def post(
        cls,
        path: str = "",
        *,
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> t.Callable[[TCallable], TCallable]:
        """
        A POST Operation method decorator
        eg.

        ```python
         @route.post()
         def post_operation(self,  create_schema: Schema):
            ...
        ```
        :param path: uniques endpoint path string
        :param auth: endpoint authentication method. default: `NOT_SET`
        :param response: `dict[status_code, schema]` or `Schema` used validated returned response. default: `None`
        :param operation_id: unique id that distinguishes `operation` in path view. default: `None`
        :param summary: describes your endpoint. default: `None`
        :param description: other description of your endpoint. default: `None`
        :param tags: list of strings for grouping endpoints only for documentation purpose. default: `None`
        :param deprecated: declares an endpoint deprecated. default: `None`
        :param by_alias: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_unset: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_defaults: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_none: pydantic schema filters applied to `response` schema object. default: `False`
        :param url_name: a name to an endpoint which can be resolved using `reverse` function in django. default: `None`
        :param include_in_schema: indicates whether an endpoint should appear on the swagger documentation
        :param permissions: collection permission classes. default: `None`
        :return: Route[POST]
        """

        def decorator(view_func: TCallable) -> TCallable:
            return cls._create_route_function(
                view_func,
                path=path,
                methods=[POST],
                auth=auth,
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                url_name=url_name,
                include_in_schema=include_in_schema,
                permissions=permissions,
                openapi_extra=openapi_extra,
                throttle=throttle,
            )

        return decorator

    @classmethod
    def delete(
        cls,
        path: str = "",
        *,
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> t.Callable[[TCallable], TCallable]:
        """
        A DELETE Operation method decorator
        eg.

        ```python
        @route.delete('/{int:some_id}')
        def delete_operation(self, some_id: int):
            ...
        ```
        :param path: uniques endpoint path string
        :param auth: endpoint authentication method. default: `NOT_SET`
        :param response: `dict[status_code, schema]` or `Schema` used validated returned response. default: `None`
        :param operation_id: unique id that distinguishes `operation` in path view. default: `None`
        :param summary: describes your endpoint. default: `None`
        :param description: other description of your endpoint. default: `None`
        :param tags: list of strings for grouping endpoints only for documentation purpose. default: `None`
        :param deprecated: declares an endpoint deprecated. default: `None`
        :param by_alias: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_unset: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_defaults: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_none: pydantic schema filters applied to `response` schema object. default: `False`
        :param url_name: a name to an endpoint which can be resolved using `reverse` function in django. default: `None`
        :param include_in_schema: indicates whether an endpoint should appear on the swagger documentation
        :param permissions: collection permission classes. default: `None`
        :return: Route[DELETE]
        """

        def decorator(view_func: TCallable) -> TCallable:
            return cls._create_route_function(
                view_func,
                path=path,
                methods=[DELETE],
                auth=auth,
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                url_name=url_name,
                include_in_schema=include_in_schema,
                permissions=permissions,
                openapi_extra=openapi_extra,
                throttle=throttle,
            )

        return decorator

    @classmethod
    def patch(
        cls,
        path: str = "",
        *,
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> t.Callable[[TCallable], TCallable]:
        """
        A PATCH Operation method decorator
        eg.

        ```python

        @route.patch('/{int:some_id}')
        def patch_operation(self,  some_id: int):
            ...
        ```
        :param path: uniques endpoint path string
        :param auth: endpoint authentication method. default: `NOT_SET`
        :param response: `dict[status_code, schema]` or `Schema` used validated returned response. default: `None`
        :param operation_id: unique id that distinguishes `operation` in path view. default: `None`
        :param summary: describes your endpoint. default: `None`
        :param description: other description of your endpoint. default: `None`
        :param tags: list of strings for grouping endpoints only for documentation purpose. default: `None`
        :param deprecated: declares an endpoint deprecated. default: `None`
        :param by_alias: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_unset: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_defaults: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_none: pydantic schema filters applied to `response` schema object. default: `False`
        :param url_name: a name to an endpoint which can be resolved using `reverse` function in django. default: `None`
        :param include_in_schema: indicates whether an endpoint should appear on the swagger documentation
        :param permissions: collection permission classes. default: `None`
        :return: Route[PATCH]
        """

        def decorator(view_func: TCallable) -> TCallable:
            return cls._create_route_function(
                view_func,
                path=path,
                methods=[PATCH],
                auth=auth,
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                url_name=url_name,
                include_in_schema=include_in_schema,
                permissions=permissions,
                openapi_extra=openapi_extra,
                throttle=throttle,
            )

        return decorator

    @classmethod
    def put(
        cls,
        path: str = "",
        *,
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> t.Callable[[TCallable], TCallable]:
        """
         A PUT Operation method decorator
        eg.

        ```python

        @route.put('/{int:some_id}')
        def put_operation(self, some_id: int):
            ...
        ```
         :param path: uniques endpoint path string
         :param auth: endpoint authentication method. default: `NOT_SET`
         :param response: `dict[status_code, schema]` or `Schema` used validated returned response. default: `None`
         :param operation_id: unique id that distinguishes `operation` in path view. default: `None`
         :param summary: describes your endpoint. default: `None`
         :param description: other description of your endpoint. default: `None`
         :param tags: list of strings for grouping endpoints only for documentation purpose. default: `None`
         :param deprecated: declares an endpoint deprecated. default: `None`
         :param by_alias: pydantic schema filters applied to `response` schema object. default: `False`
         :param exclude_unset: pydantic schema filters applied to `response` schema object. default: `False`
         :param exclude_defaults: pydantic schema filters applied to `response` schema object. default: `False`
         :param exclude_none: pydantic schema filters applied to `response` schema object. default: `False`
         :param url_name: a name to an endpoint which can be resolved using `reverse` function in django. default: `None`
         :param include_in_schema: indicates whether an endpoint should appear on the swagger documentation
         :param permissions: collection permission classes. default: `None`
         :return: Route[PUT]
        """

        def decorator(view_func: TCallable) -> TCallable:
            return cls._create_route_function(
                view_func,
                path=path,
                methods=[PUT],
                auth=auth,
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                url_name=url_name,
                include_in_schema=include_in_schema,
                permissions=permissions,
                openapi_extra=openapi_extra,
                throttle=throttle,
            )

        return decorator

    @classmethod
    def generic(
        cls,
        path: str = "",
        *,
        methods: t.List[str],
        auth: t.Any = NOT_SET,
        throttle: t.Union[BaseThrottle, t.List[BaseThrottle], NOT_SET_TYPE] = NOT_SET,
        response: t.Union[t.Any, t.List[t.Any]] = NOT_SET,
        operation_id: t.Optional[str] = None,
        summary: t.Optional[str] = None,
        description: t.Optional[str] = None,
        tags: t.Optional[t.List[str]] = None,
        deprecated: t.Optional[bool] = None,
        by_alias: bool = False,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        url_name: t.Optional[str] = None,
        include_in_schema: bool = True,
        permissions: t.Optional[
            t.List[t.Union[t.Type[BasePermission], BasePermission, t.Any]]
        ] = None,
        openapi_extra: t.Optional[t.Dict[str, t.Any]] = None,
    ) -> t.Callable[[TCallable], TCallable]:
        """
        A Custom Operation method decorator, for creating route with more than one operation
        eg.

        ```python

        @route.generic('', methods=['POST', 'GET'])
        def list_create(self, some_schema: Optional[Schema] = None):
           ...
        ```
        :param path: uniques endpoint path string
        :param methods: List of operations `GET, PUT, PATCH, DELETE, POST`
        :param auth: endpoint authentication method. default: `NOT_SET`
        :param response: `dict[status_code, schema]` or `Schema` used validated returned response. default: `None`
        :param operation_id: unique id that distinguishes `operation` in path view. default: `None`
        :param summary: describes your endpoint. default: `None`
        :param description: other description of your endpoint. default: `None`
        :param tags: list of strings for grouping endpoints only for documentation purpose. default: `None`
        :param deprecated: declares an endpoint deprecated. default: `None`
        :param by_alias: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_unset: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_defaults: pydantic schema filters applied to `response` schema object. default: `False`
        :param exclude_none: pydantic schema filters applied to `response` schema object. default: `False`
        :param url_name: a name to an endpoint which can be resolved using `reverse` function in django. default: `None`
        :param include_in_schema: indicates whether an endpoint should appear on the swagger documentation
        :param permissions: collection permission classes. default: `None`
        :return: Route[PATCH]
        """

        def decorator(view_func: TCallable) -> TCallable:
            return cls._create_route_function(
                view_func,
                path=path,
                methods=methods,
                auth=auth,
                response=response,
                operation_id=operation_id,
                summary=summary,
                description=description,
                tags=tags,
                deprecated=deprecated,
                by_alias=by_alias,
                exclude_unset=exclude_unset,
                exclude_defaults=exclude_defaults,
                exclude_none=exclude_none,
                url_name=url_name,
                include_in_schema=include_in_schema,
                permissions=permissions,
                openapi_extra=openapi_extra,
                throttle=throttle,
            )

        return decorator


route = Route
