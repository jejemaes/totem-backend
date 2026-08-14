import inspect
import typing as t
from abc import ABC, abstractmethod
from functools import wraps

from django.db.models import QuerySet
from django.http import HttpRequest
from ninja import P, Query, Schema
from ninja.constants import NOT_SET
from ninja.utils import contribute_operation_args, is_async_callable
from pydantic import ConfigDict

from core.orm.queryset import queryset_fetch_fields
from core.schemas.types import DelimiterList, MultiChoices
from core.schemas.utils import schema_public_to_orm_fields

if t.TYPE_CHECKING:
    from core.services import ServiceBase

__all__ = [
    "QueryFieldBase",
    "QueryField",
    "ListControllerQueryField",
    "query_field",
]


class QueryFieldBase(ABC):
    class Input(Schema): ...

    InputSource = Query(...)

    def __init__(
        self, *, pass_parameter: t.Optional[str] = None, **kwargs: t.Any
    ) -> None:  # pylint: disable=unused-argument
        self.pass_parameter = pass_parameter

    @abstractmethod
    def querying_field_queryset(
        self, items: t.Union[QuerySet, t.List], query_fields: Input, request: t.Optional[HttpRequest] = None
    ) -> t.Union[QuerySet, t.List]: ...


class QueryField(QueryFieldBase):

    class Input(Schema):
        pass  # do not display `query_field` as parameter if query_field_fields is not set

    def __init__(
        self,
        pass_parameter: t.Optional[str] = None,
        schema: t.Optional[t.Any] = None,
        service: t.Optional[t.Type["ServiceBase"]] = None,
    ) -> None:
        super().__init__(pass_parameter=pass_parameter)

        self.service = service
        model = service.model if service is not None else None

        self.field_map = schema_public_to_orm_fields(schema, model) if schema else {}
        self.Input = self.create_input()

    def create_input(
        self,
    ) -> t.Type[Input]:
        if not self.field_map:
            return QueryField.Input

        quoted_fnames = [f"`{fname}`" for fname in self.field_map]

        class DynamicInput(QueryFieldBase.Input):
            model_config = ConfigDict(validate_default=True)

            fields: Query[
                t.Optional[
                    t.Annotated[
                        str,
                        DelimiterList(delimiter=","),
                        MultiChoices(choices=self.field_map),
                    ]
                ],
                P(
                    description=f"Comma separated list of response field. Possible values are {','.join(quoted_fnames)}.",
                    default=",".join(list(self.field_map.keys())),
                ),
            ]  # type:ignore[type-arg,valid-type]

        return DynamicInput

    def querying_field_queryset(
        self, items: t.Union[QuerySet, t.List], query_fields: Input, request: t.Optional[HttpRequest] = None
    ) -> t.Union[QuerySet, t.List]:
        if isinstance(items, QuerySet):
            if self.service is not None and request is not None:
                return request.env.get(self.service).apply_query_fields(items, query_fields.fields)
            return queryset_fetch_fields(items, query_fields.fields)
        return items


class ListControllerQueryField(QueryField):

    def querying_field_queryset(
        self, items: t.Union[QuerySet, t.List], query_fields: QueryField.Input, request: t.Optional[HttpRequest] = None
    ) -> t.Union[QuerySet, t.List]:
        """Do nothing, as the purpose of the ListControllerQueryField is to pass the
        query_fields parameter to the controller, not to select fields on the queryset."""
        return items


def query_field(
    func_or_pgn_class: t.Any = NOT_SET, **query_field_params: t.Any
) -> t.Callable:
    """
    @api.get(...)
    @query_field(QueryField, schema=ResponseSchema, pass_parameter="query_fields")
    def my_view(request):

    """
    isfunction = inspect.isfunction(func_or_pgn_class)
    isnotset = func_or_pgn_class == NOT_SET

    query_field_class: t.Type[t.Union[QueryField, QueryFieldBase]] = (
        QueryField  # default value
    )

    if isfunction:
        return _inject_query_field(func_or_pgn_class, query_field_class)

    if not isnotset:
        query_field_class = func_or_pgn_class

    def wrapper(func: t.Callable) -> t.Any:
        return _inject_query_field(func, query_field_class, **query_field_params)

    return wrapper


def _inject_query_field(
    func: t.Callable,
    query_field_class: t.Type[t.Union[QueryFieldBase, QueryField]],
    **query_field_params: t.Any,
) -> t.Callable:
    querier = query_field_class(**query_field_params)

    if is_async_callable(func):

        @wraps(func)
        async def view_with_query_field(request: HttpRequest, **kwargs: t.Any) -> t.Any:
            queryfield_params = kwargs.pop("ninja_query_field")
            if querier.pass_parameter:
                kwargs[querier.pass_parameter] = queryfield_params

            result = await func(request, **kwargs)
            result = querier.querying_field_queryset(result, queryfield_params, request=request)
            if inspect.isawaitable(result):
                result = await result
            return result

    else:

        @wraps(func)
        def view_with_query_field(request: HttpRequest, **kwargs: t.Any) -> t.Any:
            queryfield_params = kwargs.pop("ninja_query_field")
            if querier.pass_parameter:
                kwargs[querier.pass_parameter] = queryfield_params

            result = func(request, **kwargs)
            return querier.querying_field_queryset(result, queryfield_params, request=request)

    contribute_operation_args(
        view_with_query_field,
        "ninja_query_field",
        querier.Input,
        querier.InputSource,
    )

    return view_with_query_field
