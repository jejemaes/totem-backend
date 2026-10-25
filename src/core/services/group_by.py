"""Group by: aggregates of the records a user may read, over named keys.

Odoo calls it `read_group`; the mechanism is insights' (`ExtraAnnotationQuerysetMixin`).
A service declares its *dimensions* -- the keys a client may group by, `date_month`
standing for `Trunc("date", "month")` -- and its *measures* -- the aggregates it may
ask for, `amount_sum` standing for `Sum("amount")`. A client only ever picks names:
it never sends a function, a field or an expression, so what can be computed is
exactly what the service declared.

Declared on the service, not on the queryset as in insights: the service is where
read policy lives, and a declaration may need the request -- `Trunc` reads its time
zone. Class attributes, so that a controller builds its OpenAPI enums at import
time, and checked when the class is created.
"""

import dataclasses
import re
import typing as t
import zoneinfo

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models import Avg, Count, F, Max, Min, Sum, Value
from django.db.models.functions import Cast, NullIf, Trunc

from core.orm.fields import ComputedField
from core.orm.functions import SumOverGroups

from .exceptions import ServiceValidationError, ServiceValidationMultiError

# An expression, or a callable building one from the service: what a declaration
# needs from the request (its time zone) is only known then.
ExpressionSpec = t.Any

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclasses.dataclass(frozen=True)
class Dimension:
    """A key to group by: `field` itself, `field` truncated to `truncate` (a date
    or a date-time, see `date_dimensions`), or `expression` computed from it.

    `field` is the model field read. It gives the output by default, and the label
    (`{field}` in `label` is replaced by its verbose name). A foreign key grouped
    as is comes back as the related record, resolved through its own service.
    """

    field: str
    truncate: t.Optional[str] = None
    expression: ExpressionSpec = None
    output_field: t.Optional[models.Field] = None
    label: t.Optional[str] = None


@dataclasses.dataclass(frozen=True)
class Measure:
    """An aggregate of each group. `field`, when given, is the model field it
    aggregates: its type is the output's by default, and `{field}` in `label` is
    replaced by its verbose name. Without it, `output_field` is required."""

    expression: ExpressionSpec
    field: t.Optional[str] = None
    output_field: t.Optional[models.Field] = None
    label: t.Optional[str] = None


# Always available: the number of records in each group.
COUNT = {"count": Measure(Count("pk"), output_field=models.IntegerField(), label="Count")}

DATE_KINDS = ("day", "week", "month", "quarter", "year")
DATETIME_KINDS = ("hour", *DATE_KINDS)


def date_dimensions(field, kinds=("day", "week", "month", "year"), prefix=None):
    """`<prefix>_<kind>` for each kind: `field` truncated to the day, the week...

    A date-time is truncated in the time zone of the request, so that a day is the
    user's day, not UTC's. A date has none: django refuses `tzinfo` on it.
    """
    prefix = prefix or field
    return {
        f"{prefix}_{kind}": Dimension(field, truncate=kind, label=f"{{field}} ({kind})")
        for kind in kinds
    }


def number_measures(field, functions=("sum", "avg", "min", "max"), prefix=None):
    """`<prefix>_<function>` for each function, among sum, avg, min and max.

    An average is cast to a float, as in insights: over integers postgres returns a
    numeric of arbitrary scale, which no output type of the field would hold.
    """
    prefix = prefix or field
    aggregates = {"sum": Sum, "min": Min, "max": Max}
    measures = {}
    for function in functions:
        name = f"{prefix}_{function}"
        label = f"{function.capitalize()} of {{field}}"
        if function == "avg":
            measures[name] = Measure(
                Cast(Avg(field), models.FloatField()), field, models.FloatField(), label
            )
        else:
            measures[name] = Measure(aggregates[function](field), field, label=label)
    return measures


def share_measure(field, exclude, name=None):
    """`<field>_share`: the percentage (0-100) the sum of `field` of a group is of
    the sum over the groups sharing every key but those in `exclude`.

    Grouped by `[date_month, category]` with `exclude=["category"]`, the share of
    each category in its month. A key of `exclude` the client does not group by
    leaves every group alone in its partition: 100. NULL when the total is zero.
    """
    return {
        name or f"{field}_share": Measure(
            lambda service: Cast(
                Cast(Sum(field), models.FloatField())
                * Value(100.0)
                / NullIf(SumOverGroups(field, exclude=exclude), Value(0)),
                models.FloatField(),
            ),
            field,
            models.FloatField(),
            f"Share of {{field}} (%, across {', '.join(exclude)})",
        )
    }


@dataclasses.dataclass(frozen=True)
class BoundDeclaration:
    """A dimension or a measure checked against its model, with what `group_by`
    and the controller read from it."""

    name: str
    expression: ExpressionSpec  # None: a column of the model, grouped as is
    output_field: models.Field
    label: str
    related_model: t.Optional[t.Type[models.Model]] = None  # a relation, rendered as its record

    def build(self, service):
        if callable(self.expression) and not hasattr(self.expression, "resolve_expression"):
            return self.expression(service)
        return self.expression


class GroupByMixin:
    """Provides `group_by`, over `group_by_dimensions` and `group_by_measures`.

    Reached through the *read* access rules: a group sums records the user may
    read, and nothing else.
    """

    group_by_dimensions: t.ClassVar[t.Dict[str, Dimension]] = {}
    group_by_measures: t.ClassVar[t.Dict[str, Measure]] = {}

    # Filled when the class is created, from the declarations above.
    _group_by_dimensions: t.ClassVar[t.Dict[str, BoundDeclaration]] = {}
    _group_by_measures: t.ClassVar[t.Dict[str, BoundDeclaration]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        model = getattr(cls, "model", None)
        if model is None:
            return
        # At declaration, so a typo fails at startup rather than on a request.
        cls._group_by_dimensions = {
            name: _bind_dimension(cls, model, name, dimension)
            for name, dimension in cls.group_by_dimensions.items()
        }
        cls._group_by_measures = {
            name: _bind_measure(cls, model, name, measure)
            for name, measure in {**COUNT, **cls.group_by_measures}.items()
        }
        both = set(cls._group_by_dimensions) & set(cls._group_by_measures)
        if both:
            raise ImproperlyConfigured(
                f"{cls.__name__}: {sorted(both)} are both a dimension and a measure."
            )

    async def group_by(
        self,
        dimensions: t.List[str],
        measures: t.List[str],
        filters=None,
        ordering: t.List[str] = None,
        limit: t.Optional[int] = None,
        offset: int = 0,
        relation_fields: t.Optional[t.Dict[str, t.List[str]]] = None,
    ) -> t.Tuple[int, t.List[t.Dict]]:
        """The groups of the records the acting user may read, `filters` selects,
        by the values of `dimensions`, with the values of `measures` of each.

        Returns the total number of groups, and the groups of the page `limit` and
        `offset` select, each a dict keyed by the names asked. `ordering` names
        dimensions or measures asked, `-` for descending; the dimensions not named
        follow, so that a page always holds the same groups. NULLs come last.

        A dimension on a foreign key comes back as the related record, read
        through its service: a record the user may not read stays a bare pk, and
        none stays None. `relation_fields` maps such a dimension to the ORM lookups
        of the record to load, see `display_name`; without it the whole record is,
        and with no lookup at all none is: the pk stays, at no query.

        Raises `ServiceValidationMultiError` for a name not declared or repeated,
        an ordering on a name not asked, an offset without a limit.
        """
        self._group_by_check(dimensions, measures, ordering, limit, offset)

        scoped = await self.apply_access_rules(self.get_queryset(), "read")
        if filters:
            scoped = self._apply_filters(scoped, filters)
        # Through the pks, not the scoped queryset itself: a rule or a filter that
        # crosses a to-many relation (`account__teams__in=...`) joins one row per
        # match, which `.filter()` keeps -- each record is then counted, and summed,
        # once per match, *inside* the GROUP BY, with no error anywhere. DISTINCT
        # cannot undo it: it applies to the groups, after the sums. A `pk IN
        # (subquery)` is a semi-join: it selects, and never multiplies.
        # `order_by()`: a `Meta.ordering` would join the GROUP BY, one group per row.
        queryset = self.get_queryset().filter(pk__in=scoped.values("pk")).order_by()

        annotations = {
            name: self._group_by_dimensions[name].build(self)
            for name in dimensions
            if self._group_by_dimensions[name].expression is not None
        }
        if annotations:
            queryset = queryset.annotate(**annotations)
        queryset = queryset.values(*dimensions)
        total = await queryset.distinct().acount()

        queryset = queryset.annotate(**{
            name: self._group_by_measures[name].build(self) for name in measures
        }).order_by(*self._group_by_ordering(dimensions, ordering))
        if limit is not None:
            queryset = queryset[offset:offset + limit]
        rows = [row async for row in queryset]

        await self._group_by_resolve_relations(rows, dimensions, relation_fields or {})
        return total, rows

    def _group_by_check(self, dimensions, measures, ordering, limit, offset):
        error = ServiceValidationError({})
        for key, names, declared in (
            ("dimensions", dimensions, self._group_by_dimensions),
            ("measures", measures, self._group_by_measures),
        ):
            if not names:
                error.add_message(f"At least one of {sorted(declared)} is required.", key=key)
            unknown = [name for name in names if name not in declared]
            if unknown:
                error.add_message(
                    f"Unknown value(s): {','.join(unknown)}. Possible values are "
                    f"{','.join(sorted(declared))}.",
                    key=key,
                )
            repeated = sorted({name for name in names if names.count(name) > 1})
            if repeated:
                error.add_message(f"Repeated value(s): {','.join(repeated)}.", key=key)

        ordered = [_ordering_name(token) for token in ordering or []]
        asked = set(dimensions) | set(measures)
        unasked = [name for name in ordered if name not in asked]
        if unasked:
            error.add_message(
                f"Ordering on value(s) not grouped by nor measured: {','.join(unasked)}.",
                key="ordering",
            )
        repeated = sorted({name for name in ordered if ordered.count(name) > 1})
        if repeated:
            error.add_message(f"Repeated value(s): {','.join(repeated)}.", key="ordering")

        if offset and limit is None:
            error.add_message("An offset requires a limit.", key="offset")

        if error:
            raise ServiceValidationMultiError({"__all__": error}, code="invalid_group_by")

    def _group_by_ordering(self, dimensions, ordering):
        """Order by expressions, not names: `order_by("category")` follows the
        `Meta.ordering` of the category, a join whose columns django adds to the
        GROUP BY -- one group per category name. `F("category")` is the column."""
        terms = []
        named = set()
        for token in ordering or []:
            name = _ordering_name(token)
            named.add(name)
            expression = F(name)
            terms.append(
                expression.desc(nulls_last=True) if token.startswith("-")
                else expression.asc(nulls_last=True)
            )
        terms.extend(F(name).asc(nulls_last=True) for name in dimensions if name not in named)
        return terms

    async def _group_by_resolve_relations(self, rows, dimensions, relation_fields):
        """Replace the pks of the relation dimensions by their records, one query
        per dimension, through the related service: the records the user may read,
        as everywhere a relation is resolved."""
        for name in dimensions:
            related_model = self._group_by_dimensions[name].related_model
            if related_model is None or relation_fields.get(name, True) == []:
                continue
            pks = list({row[name] for row in rows if row[name] is not None})
            if not pks:
                continue
            service = self.env[related_model]
            if name in relation_fields:
                records = await service.display_name(pks, relation_fields[name])
            else:
                records = [record async for record in await service.browse(pks)]
            by_pk = {record.pk: record for record in records}
            for row in rows:
                if row[name] is not None:
                    row[name] = by_pk.get(row[name], row[name])


def _ordering_name(token):
    return token[1:] if token.startswith("-") else token


def _check_name(service_class, name, kind):
    if not NAME_PATTERN.match(name):
        raise ImproperlyConfigured(
            f"{service_class.__name__}: the {kind} {name!r} is no valid name "
            f"({NAME_PATTERN.pattern})."
        )


def _get_field(service_class, model, name, kind, field_name):
    try:
        field = model._meta.get_field(field_name)
    except FieldDoesNotExist:
        raise ImproperlyConfigured(
            f"{service_class.__name__}: the {kind} {name!r} reads {field_name!r}, which "
            f"is no field of {model.__name__}."
        )
    if field.many_to_many or field.one_to_many or not field.concrete:
        raise ImproperlyConfigured(
            f"{service_class.__name__}: the {kind} {name!r} reads {field_name!r}, which "
            f"is no column of {model.__name__}: a to-many relation would multiply the "
            f"records it groups."
        )
    return field


def _is_field_name(model, name):
    try:
        model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return True


def _bare_output_field(field):
    """A field of the same type as `field`, without its validators.

    A response validates what it serializes: the `max_digits` of a column would
    refuse a sum larger than any single row, its `max_length` and `choices` say
    nothing of an aggregate. A computed or generated field holds its `output_field`.
    """
    if isinstance(field, (ComputedField, models.GeneratedField)):
        field = field.output_field
    return type(field)()


def _label(label, field):
    """`label`, `{field}` replaced by the verbose name of `field`, capitalized."""
    if field is not None:
        label = label.replace("{field}", str(field.verbose_name))
    return label[:1].upper() + label[1:]


def _truncation(field, kind):
    """The expression of `Dimension.truncate`, built per request: a date-time is
    truncated in the time zone of the request."""
    if isinstance(field, models.DateTimeField):
        return lambda service: Trunc(field.name, kind, tzinfo=zoneinfo.ZoneInfo(service.tz))
    return lambda service: Trunc(field.name, kind)


def _bind_dimension(service_class, model, name, dimension):
    _check_name(service_class, name, "dimension")
    field = _get_field(service_class, model, name, "dimension", dimension.field)

    expression = dimension.expression
    if dimension.truncate is not None:
        # `DateTimeField` is a `DateField`: tested first.
        if isinstance(field, models.DateTimeField):
            kinds = DATETIME_KINDS
        elif isinstance(field, models.DateField):
            kinds = DATE_KINDS
        else:
            kinds = ()
        if dimension.truncate not in kinds:
            raise ImproperlyConfigured(
                f"{service_class.__name__}: the dimension {name!r} truncates "
                f"{field.name!r} to the {dimension.truncate!r}, which is none of "
                f"{list(kinds)}."
            )
        expression = _truncation(field, dimension.truncate)
    elif expression is None and name != field.name:
        expression = F(field.name)  # another name for the column

    # An annotation may not shadow a field: django refuses it.
    if expression is not None and _is_field_name(model, name):
        raise ImproperlyConfigured(
            f"{service_class.__name__}: the dimension {name!r} is computed but bears the "
            f"name of a field of {model.__name__}."
        )

    related_model = None
    if dimension.expression is None and dimension.truncate is None and field.is_relation:
        related_model = field.related_model
    output_field = dimension.output_field
    if output_field is None:
        output_field = field if related_model is not None else _bare_output_field(field)

    return BoundDeclaration(
        name=name,
        expression=expression,
        output_field=output_field,
        label=_label(dimension.label or "{field}", field),
        related_model=related_model,
    )


def _bind_measure(service_class, model, name, measure):
    _check_name(service_class, name, "measure")
    if _is_field_name(model, name):
        raise ImproperlyConfigured(
            f"{service_class.__name__}: the measure {name!r} bears the name of a field "
            f"of {model.__name__}."
        )
    field = None
    if measure.field is not None:
        field = _get_field(service_class, model, name, "measure", measure.field)
    output_field = measure.output_field
    if output_field is None:
        if field is None:
            raise ImproperlyConfigured(
                f"{service_class.__name__}: the measure {name!r} declares neither the "
                f"field it aggregates nor its output_field."
            )
        output_field = _bare_output_field(field)
    return BoundDeclaration(
        name=name,
        expression=measure.expression,
        output_field=output_field,
        label=_label(measure.label or name, field),
    )
