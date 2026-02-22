import logging
from collections import OrderedDict
from typing import Any, Generic, List, Optional, Type, TypeVar, Union

from django.core.paginator import InvalidPage, Page, Paginator
from django.db.models import QuerySet
from django.http import Http404, HttpRequest
from ninja import Schema
from ninja.pagination import PaginationBase, paginate  # noqa
from ninja.types import DictStrAny
from pydantic import Field
from pydantic.networks import AnyUrl

from core.orm.queryset import model_instance_to_dict
from core.utils.urls import remove_query_param, replace_query_param

logger = logging.getLogger()

T = TypeVar("T")

PAGINATION_PER_PAGE = 20


class PageNumberPagination(PaginationBase):

    items_attribute = "results"

    class Input(Schema):
        page: int = Field(1, gt=0)
        page_size: int = Field(100, lt=200)

    class Output(Schema, Generic[T]):
        count: int
        next: Optional[str]
        previous: Optional[str]
        results: List[T]

    page_query_param = "page"
    page_size_query_param = "page_size"

    max_page_size = 200
    paginator_class = Paginator

    def __init__(
        self,
        page_size: int = PAGINATION_PER_PAGE,
        max_page_size: Optional[int] = None,
        pass_parameter: Optional[str] = None,
    ) -> None:
        super().__init__(pass_parameter=pass_parameter)
        self.page_size = page_size
        self.max_page_size = max_page_size or 200
        self.Input = self.create_input()  # type:ignore

    def create_input(self) -> Type[Input]:
        class DynamicInput(PageNumberPagination.Input):
            page: int = Field(1, gt=0)
            page_size: int = Field(self.page_size, lt=self.max_page_size)

        return DynamicInput

    def paginate_queryset(
        self,
        queryset: QuerySet,
        pagination: Input,
        request: Optional[HttpRequest] = None,
        **params: DictStrAny,
    ) -> Any:
        assert request, "request is required"
        current_page_number = pagination.page
        paginator = self.paginator_class(queryset, pagination.page_size)
        try:
            url = request.build_absolute_uri()
            page: Page = paginator.page(current_page_number)
            return self.get_paginated_response(base_url=url, page=page)
        except InvalidPage as exc:  # pragma: no cover
            msg = "Invalid page. {page_number} {message}".format(
                page_number=current_page_number, message=str(exc)
            )
            raise Http404(msg) from exc

    def get_paginated_response(self, *, base_url: str, page: Page) -> DictStrAny:
        res = dict(
            [
                ("count", page.paginator.count),
                ("next", self.get_next_link(base_url, page=page)),
                ("previous", self.get_previous_link(base_url, page=page)),
                ("results", [model_instance_to_dict(r) for r in page]),
            ]
        )
        return res

    def get_next_link(self, url: str, page: Page) -> Optional[str]:
        if not page.has_next():
            return None
        page_number = page.next_page_number()
        return replace_query_param(url, self.page_query_param, page_number)

    def get_previous_link(self, url: str, page: Page) -> Optional[str]:
        if not page.has_previous():
            return None
        page_number = page.previous_page_number()
        if page_number == 1:
            return remove_query_param(url, self.page_query_param)
        return replace_query_param(url, self.page_query_param, page_number)
