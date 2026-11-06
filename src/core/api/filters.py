"""Multi-valued list filters: `?account=<id>,<id>,null`.

A field typed `MultiValue(item_type)` on a `FilterSchema` of this module takes a
comma-separated list of values, each validated as `item_type`, and filters with
`<q>__in`. The `NULL_SENTINEL` token among them adds `<q>__isnull=True`: the
records whose relation (or choice) is empty. A single value filters as it did
when the field was single-valued, so turning a field into a `MultiValue` breaks
no caller -- `null` alone changes meaning, from a value to "empty".

How it rides on ninja:

* The field's type is a list, so ninja reads the query parameter with
  `QueryDict.getlist()` (`ninja.signature.details.detect_collection_fields`):
  `?id=a&id=b` keeps working, and each item is split on commas in turn. A
  single-valued field gets `QueryDict[key]` instead, which keeps the LAST of
  repeated values: those requests now filter on all of them.
* The same schema is the `filters` body of `POST /group-by/`, where the value is
  a JSON string (`"a,b"`, the documented form) or a JSON list.
* The OpenAPI document declares a `string`, not an array: the type the
  single-valued field had, so a generated client sees no change of contract.
  Repeated parameters are tolerated, not advertised.

Not built on `core.schemas.types.DelimiterList`: that one splits AFTER the type is
validated, so it only works on `str`, while a pk must be split BEFORE each item is
validated as a ULID, a UUID or an int, and the sentinel turned into `None`.
"""

import typing as t
from dataclasses import dataclass
from functools import partial

import ninja
from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q
from pydantic import BeforeValidator, WithJsonSchema
from pydantic.fields import FieldInfo

__all__ = [
    "NULL_SENTINEL",
    "FilterSchema",
    "MultiValue",
]

NULL_SENTINEL = "null"


@dataclass(frozen=True)
class _MultiValue:
    """Marks a `MultiValue` field in its `Annotated` metadata, for
    `FilterSchema._resolve_field_expression` to recognize it."""

    allow_null: bool


def _split_values(value: t.Any, allow_null: bool) -> t.Optional[t.List[t.Any]]:
    if value is None:
        return None
    items = value if isinstance(value, (list, tuple)) else [value]
    values = []
    for item in items:
        if not isinstance(item, str):
            # An int pk in a JSON body: the item type validates it.
            values.append(item)
            continue
        for part in item.split(","):
            part = part.strip()
            if not part:
                continue
            # Without `allow_null` the token is left as is, for the item type to
            # refuse it (422) rather than to filter on a pk named "null".
            values.append(None if allow_null and part == NULL_SENTINEL else part)
    # `?account=` filters on nothing, as an absent parameter does.
    return values or None


def MultiValue(item_type: t.Any, *, allow_null: bool = True) -> t.Any:  # pylint: disable=invalid-name
    """The type of a multi-valued filter field, whose items are `item_type`::

        user: MultiValue(uuid.UUID) = Field(None, q="user__id")
        id: MultiValue(ULID, allow_null=False) = Field(None, q="id")

    `allow_null=False` for a lookup that is never empty, a pk: `null` is then
    refused instead of matching nothing.

    Not for a lookup across a to-many relation (`tags__id`) yet: `IN` joins it, so
    a record matching through two related rows would come out twice. That one
    needs the filter applied as an `EXISTS` subquery.
    """
    inner = t.Optional[item_type] if allow_null else item_type
    return t.Annotated[
        t.Optional[t.List[inner]],
        BeforeValidator(partial(_split_values, allow_null=allow_null)),
        WithJsonSchema({"type": "string"}),
        _MultiValue(allow_null),
    ]


class FilterSchema(ninja.FilterSchema):
    """The base of every filter schema of the project: ninja's, plus `MultiValue`
    fields. On ninja's own base, such a field would compile to `Q(lookup=[...])`.

    A `filter_<name>` method still wins over the generic lookup, and receives the
    list of values.
    """

    def _resolve_field_expression(self, field_name: str, field_value: t.Any, field: FieldInfo) -> Q:
        is_multi = any(isinstance(meta, _MultiValue) for meta in field.metadata)
        if not is_multi or callable(getattr(self, f"filter_{field_name}", None)):
            return super()._resolve_field_expression(field_name, field_value, field)

        lookup = (field.json_schema_extra or {}).get("q") or field_name
        if not isinstance(lookup, str):
            # `IN` over several lookups ORed is no filter anybody asked for yet.
            raise ImproperlyConfigured(
                f"Field {field_name} of {self.__class__.__name__} is a MultiValue: its 'q' "
                f"must be a single lookup, not {lookup!r}."
            )
        if lookup.startswith("__"):
            lookup = f"{field_name}{lookup}"

        if field_value is None:
            return Q()
        values = [value for value in field_value if value is not None]
        q = Q()
        if values:
            q |= Q(**{f"{lookup}__in": values})
        if len(values) < len(field_value):
            q |= Q(**{f"{lookup}__isnull": True})
        return q
