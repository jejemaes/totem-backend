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
from core.orm.queryset import queryset_order_by_fields

__all__ = [
    "OrderingBase",
    "Ordering",
    "ordering",
]


class OrderingBase(ABC):
    class Input(Schema): ...

    InputSource = Query(...)

    def __init__(self, *, pass_parameter: Optional[str] = None, **kwargs: Any) -> None:
        self.pass_parameter = pass_parameter

    @abstractmethod
    def ordering_queryset(
        self, items: Union[QuerySet, List], ordering_input: Any
    ) -> Union[QuerySet, List]: ...


class Ordering(OrderingBase):
    class Input(Schema):
        pass  # do not display `ordering` as parameter if ordering_fields is not set

    def __init__(
        self,
        pass_parameter: Optional[str] = None,
        field_map: Optional[dict[str, str]] = None,
        default_ordering_fields: Optional[List[str]] = ["pk"],
    ) -> None:
        super().__init__(pass_parameter=pass_parameter)
        self.field_map = field_map or {}
        self.default_ordering_fields = default_ordering_fields or ["pk"]
        self.Input = self.create_input()  # type:ignore

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
            ]  # type:ignore[type-arg,valid-type]

        return DynamicInput

    def ordering_queryset(
        self, items: Union[QuerySet, List], ordering_input: Input
    ) -> Union[QuerySet, List]:
        ordering_ = ordering_input.ordering
        if ordering_:
            if isinstance(items, QuerySet):
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
    execute_ordering=True,
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

            if execute_ordering:
                items = await orderator.ordering_queryset(
                    items, ordering_input=ordering_params
                )
            return items

    else:

        @wraps(func)
        def view_with_ordering(request: HttpRequest, **kwargs: Any) -> Any:
            ordering_params = kwargs.pop("ninja_ordering")
            if orderator.pass_parameter:
                kwargs[orderator.pass_parameter] = ordering_params

            items = func(request, **kwargs)

            if execute_ordering:
                items = orderator.ordering_queryset(
                    items, ordering_input=ordering_params
                )
            return items

    contribute_operation_args(
        view_with_ordering,
        "ninja_ordering",
        orderator.Input,
        orderator.InputSource,
    )

    return view_with_ordering
