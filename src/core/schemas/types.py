# pylint: disable=unused-argument
import typing as t
from dataclasses import dataclass

from django.db.models import Model
from ninja.types import DictStrAny
from pydantic import BaseModel, GetCoreSchemaHandler
from pydantic_core import core_schema as cs
from typing_extensions import get_args, get_origin


class ExtraFieldInfos(BaseModel):
    alias: t.Optional[str] = None
    title: t.Optional[str] = None
    description: t.Optional[str] = None
    pattern: t.Optional[str] = None
    gt: t.Optional[int] = None
    ge: t.Optional[int] = None
    lt: t.Optional[int] = None
    le: t.Optional[int] = None
    min_length: t.Optional[int] = None
    max_length: t.Optional[int] = None
    max_digits: t.Optional[int] = None


class AnyObject:
    @classmethod
    def __get_pydantic_core_schema__(
        cls, source: t.Any, handler: t.Callable[..., t.Any]
    ) -> t.Any:
        return cs.with_info_plain_validator_function(cls.validate)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, schema: t.Any, handler: t.Callable[..., t.Any]
    ) -> DictStrAny:
        return {"type": "object"}

    @classmethod
    def validate(cls, value: t.Any, _: t.Any) -> t.Any:
        return value


SchemaKey = t.Tuple[t.Type[Model], str, int, str, str, str, str]

T = t.TypeVar("T")


@dataclass
class DelimiterList:

    item_type: t.Optional[t.Type] = str
    delimiter: str = ","

    def __get_pydantic_core_schema__(
        self,
        _source_type: t.Any,
        _handler: t.Any,
    ) -> dict:
        origin = get_origin(_source_type)
        if origin is None:
            origin = _source_type
            item_tp = None
        else:
            item_tp = get_args(_source_type)[0]

        item_tp = item_tp or origin

        if item_tp not in [t.List[str], str]:
            raise ValueError(
                "DelimiterList can only be used with List[str] or str type annotations."
            )

        schema = _handler(
            _source_type
        )  # get the CoreSchema from the type / inner constraints

        return cs.no_info_after_validator_function(
            self.validate,
            schema,
        )

    def validate(self, value: str) -> t.List[t.Any]:
        items = []
        if isinstance(value, str):
            items = value.split(self.delimiter)
        elif isinstance(value, list):
            items = list(self.delimiter.join(value).split(self.delimiter))
        else:
            raise ValueError("Value must be a string or a list of strings.")
        return [self.item_type(item) for item in items]


@dataclass
class MultiChoices:
    choices: t.Union[t.Sequence[str], t.Dict[str, t.Any]]

    def __get_pydantic_core_schema__(
        self, source: type[t.Any], handler: GetCoreSchemaHandler
    ) -> cs.CoreSchema:
        if not self.choices:
            raise ValueError("Choices may not be empty")

        schema = handler(source)  # get the CoreSchema from the type / inner constraints
        return cs.no_info_after_validator_function(
            self.validate,
            schema,
        )

    def validate(self, values: t.List[str]) -> str:
        # check if all values are in choices
        allowed = self.choices
        if isinstance(self.choices, dict):
            allowed = list(self.choices.keys())

        forbidden = [val for val in values if val not in allowed]
        if forbidden:
            raise ValueError(f"{','.join(forbidden)} are invalid choices.")

        # convert values to their corresponding values if choices is a dict
        if isinstance(self.choices, dict):
            values = [self.choices[val] for val in values]

        return values
