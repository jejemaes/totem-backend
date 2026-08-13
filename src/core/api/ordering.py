import inspect
import typing as t
from abc import ABC, abstractmethod
from functools import wraps
from operator import attrgetter, itemgetter
from typing import Any, Callable, List, Optional, Tuple, Type, Union

from django.db.models import QuerySet
from django.http import HttpRequest
from ninja import P, Query, Schema
from ninja.constants import NOT_SET
from ninja.utils import contribute_operation_args, is_async_callable
from pydantic import ConfigDict

from core.schemas.types import DelimiterList, MultiChoices
from core.schemas.utils import schema_orm_to_public_fields
from core.orm.queryset import queryset_order_by_fields

if t.TYPE_CHECKING:
    from core.services import ServiceBase

__all__ = [
    "OrderingBase",
    "Ordering",
    "ListControllerOrdering",
    "ordering",
]


class OrderingBase(ABC):
    class Input(Schema): ...

    InputSource = Query(...)

    def __init__(self, *, pass_parameter: Optional[str] = None, **kwargs: Any) -> None:
        self.pass_parameter = pass_parameter

    @abstractmethod
    def ordering_queryset(
        self, items: Union[QuerySet, List], ordering_input: Any, request: Optional[HttpRequest] = None
    ) -> Union[QuerySet, List]: ...


class Ordering(OrderingBase):
    class Input(Schema):
        pass  # do not display `ordering` as parameter if ordering_fields is not set

    def __init__(
        self,
        pass_parameter: Optional[str] = None,
        schema: Optional[Any] = None,
        service: Optional[Type["ServiceBase"]] = None,
        ordering_fields: Optional[List[str]] = None,
        default_ordering_fields: Optional[List[str]] = None,
    ) -> None:

        super().__init__(pass_parameter=pass_parameter)

        self.service = service
        model = service.model if service is not None else None

        orm_to_public = schema_orm_to_public_fields(schema, model) if schema else {}
        field_map = {
            orm_to_public.get(fname, fname): fname for fname in (ordering_fields or [])
        }

        # defaults are declared with ORM field names but go through the same validation as a
        # client-sent `?ordering=`, which only accepts public tokens
        orm_to_token = {orm: token for token, orm in field_map.items()}
        translated_defaults = []
        for fname in default_ordering_fields or []:
            descending = fname.startswith("-")
            name = fname[1:] if descending else fname
            token = orm_to_token.get(name, name)
            translated_defaults.append(f"-{token}" if descending else token)

        self.field_map = field_map
        self.default_ordering_fields = translated_defaults or ["pk"]
        self.Input = self.create_input()  # type: ignore

    def create_input(self) -> Type[Input]:
        if not self.field_map:
            return Ordering.Input

        allowed_field_map = dict(self.field_map)
        allowed_field_map.update({f"-{k}": f"-{v}" for k, v in self.field_map.items()})
        quoted_fnames = [f"`{fname}`" for fname in allowed_field_map]

        class DynamicInput(Ordering.Input):
            model_config = ConfigDict(validate_default=True)

            ordering: Query[
                t.Optional[
                    t.Annotated[
                        str,
                        DelimiterList(delimiter=","),
                        MultiChoices(choices=allowed_field_map),
                    ]
                ],
                P(
                    default=",".join(self.default_ordering_fields),
                    description=f"Comma separated list of fields to order by. Prefix with '-' for descending order. Possible values are {','.join(quoted_fnames)}.",
                ),
            ]  # type: ignore[type-arg,valid-type]

        return DynamicInput

    def ordering_queryset(
        self, items: Union[QuerySet, List], ordering_input: Input, request: Optional[HttpRequest] = None
    ) -> Union[QuerySet, List]:
        ordering_ = ordering_input.ordering
        if ordering_:
            if isinstance(items, QuerySet):
                if self.service is not None and request is not None:
                    # "nulls last" is the service's call alone (`ordering_fields_nulls_last`,
                    # see `ServiceBase.apply_ordering`) -- never something this decorator
                    # or a controller could override per field.
                    return request.env.get(self.service).apply_ordering(items, ordering_)
                return queryset_order_by_fields(items, ordering_)
            elif isinstance(items, list) and items:

                def multisort(xs: List, specs: List[Tuple[str, bool]]) -> List:
                    orerator = itemgetter if isinstance(xs[0], dict) else attrgetter
                    for key, reverse in reversed(specs):
                        xs.sort(key=orerator(key), reverse=reverse)
                    return xs

                return multisort(
                    items,
                    [
                        (o[int(o.startswith("-")) :], o.startswith("-"))
                        for o in ordering_
                    ],
                )
        return items


class ListControllerOrdering(Ordering):

    def ordering_queryset(
        self, items: Union[QuerySet, List], ordering_input: Ordering.Input, request: Optional[HttpRequest] = None
    ) -> Union[QuerySet, List]:
        """Do nothing, as the purpose of the ListControllerOrdering is to pass the ordering
        parameter to the controller, not to order the queryset."""
        return items


def ordering(func_or_pgn_class: Any = NOT_SET, **orderator_params: Any) -> Callable:
    """
    @api.get(...
    @ordering
    def my_view(request):

    or

    @api.get(...
    @ordering(OrderingCustom)
    def my_view(request):

    """

    isfunction = inspect.isfunction(func_or_pgn_class)
    isnotset = func_or_pgn_class == NOT_SET

    ordering_class: Type[Union[OrderingBase, OrderingBase]] = Ordering # default value

    if isfunction:
        return _inject_ordering(func_or_pgn_class, ordering_class)

    if not isnotset:
        ordering_class = func_or_pgn_class

    def wrapper(func: Callable) -> Any:
        return _inject_ordering(func, ordering_class, **orderator_params)

    return wrapper


def _inject_ordering(
    func: Callable,
    ordering_class: Type[Union[OrderingBase]],
    **orderator_params: Any,
) -> Callable:
    orderator = ordering_class(**orderator_params)
    if is_async_callable(func):

        @wraps(func)
        async def view_with_ordering(request: HttpRequest, **kwargs: Any) -> Any:
            ordering_params = kwargs.pop("ninja_ordering")
            if orderator.pass_parameter:
                kwargs[orderator.pass_parameter] = ordering_params

            items = await func(request, **kwargs)

            items = orderator.ordering_queryset(items, ordering_input=ordering_params, request=request)
            if inspect.isawaitable(items):
                items = await items
            return items

    else:

        @wraps(func)
        def view_with_ordering(request: HttpRequest, **kwargs: Any) -> Any:
            ordering_params = kwargs.pop("ninja_ordering")
            if orderator.pass_parameter:
                kwargs[orderator.pass_parameter] = ordering_params

            items = func(request, **kwargs)

            items = orderator.ordering_queryset(items, ordering_input=ordering_params, request=request)
            return items

    contribute_operation_args(
        view_with_ordering,
        "ninja_ordering",
        orderator.Input,
        orderator.InputSource,
    )

    return view_with_ordering
