"""Registry accessors and the SQL building blocks shared by every computed field.

Nothing here imports `field.py`: the field module depends on this one, not the
other way round, so the four registries are read by attribute name.
"""

import typing as t

from django.db import models
from django.db.models import OuterRef, Subquery

if t.TYPE_CHECKING:
    from .field import ComputedField

# The four registries `ComputedField.contribute_to_class` fills on `Model._meta`.
# Every computed field sits in exactly two of them: one per storage strategy, one
# per computation strategy.
STORED = "stored_computed_fields"
VIRTUAL = "virtual_computed_fields"
ANNOTATION = "computed_annotation_fields"
PREFETCH = "computed_prefetch_fields"
REGISTRIES = (STORED, VIRTUAL, ANNOTATION, PREFETCH)


def computed_fields(model, registry: str) -> t.Dict[str, "ComputedField"]:
    """The `{name: field}` registry of `model`, empty for a model without any.

    The attribute only exists on models declaring a computed field, so reading it
    through here is what lets generic code ask every model the same question.
    """
    return getattr(model._meta, registry, {})


def get_computed_field(model, name: str) -> t.Optional["ComputedField"]:
    """The computed field `name` of `model`, stored or virtual, or None."""
    return computed_fields(model, STORED).get(name) or computed_fields(model, VIRTUAL).get(name)


def has_computed_fields(model) -> bool:
    return bool(computed_fields(model, STORED) or computed_fields(model, VIRTUAL))


def alias_for(field: "ComputedField") -> str:
    # Not `__<name>`: a double underscore is a lookup separator for `values()`.
    return f"computed_value_{field.name}"


def as_subquery(field: "ComputedField") -> Subquery:
    """The field's annotation, as a subquery correlated on the row's own pk.

    `annotation_method` is written exactly like an argument to `.annotate()`, joins
    and aggregates included: `Sum(F("lines__quantity") * F("lines__unit_price"))`.
    Used raw, that expression is refused by an `UPDATE` (django raises "Joined field
    references are not permitted in this query" on any relation), and in a SELECT it
    adds a GROUP BY plus joins that multiply each other as soon as two computed
    fields cross different multi-valued relations. Wrapping it in a subquery over
    the model itself solves both: `.annotate()` resolves the joins and the grouping
    inside, the outer query stays a plain one-row-per-pk read or write, and a given
    `annotation_method` yields the same value stored or virtual.

    The price is a self-join on the primary key per row, i.e. an index lookup.
    """
    model = field.model
    alias = alias_for(field)
    inner = (
        model._base_manager
        .filter(pk=OuterRef("pk"))
        # A `Meta.ordering` would leak into the GROUP BY of the aggregate.
        .order_by()
        .annotate(**{alias: field.get_annotation()})
        .values(alias)
    )
    return Subquery(inner, output_field=field.output_field)


def bulk_refresh_fields(model, pks: t.Iterable, fields: t.Iterable["ComputedField"]) -> None:
    """Recompute and persist the given stored fields of `model` on the rows `pks`.

    Annotation fields cost one `UPDATE` in total, whatever the number of rows or of
    fields: they are all set by the same statement. Prefetch fields cost one read of
    the rows plus one `bulk_update`, since their value comes out of Python.

    Goes through `_base_manager`: a refresh must reach every row, including the
    ones a default manager would hide.
    """
    pks = list(pks)
    fields = list(fields)
    if not pks or not fields:
        return

    by_annotation = [f for f in fields if f.annotation_method is not None]
    by_prefetch = [f for f in fields if f.prefetch_method is not None]

    if by_annotation:
        model._base_manager.filter(pk__in=pks).update(
            **{f.name: as_subquery(f) for f in by_annotation}
        )

    if by_prefetch:
        # Full rows rather than `.only()`: a prefetch method is arbitrary python and
        # may read any column of the instance it is given.
        instances = list(model._base_manager.filter(pk__in=pks))
        for field in by_prefetch:
            field.run_prefetch(instances)
        model._base_manager.bulk_update(instances, [f.name for f in by_prefetch])


def prime_computed_values(instances: t.List[models.Model], names: t.Iterable[str] = None) -> None:
    """Load computed values onto instances already in memory.

    For instances that were built rather than fetched -- the result of a
    `bulk_create` -- and are about to be serialized where no query may run (an
    async route serializes outside of any `sync_to_async`). Stored values are read
    back from their column, since the in-memory instance still holds whatever it was
    built with; virtual ones are computed.

    One query for every stored and annotated value together, plus one call per
    prefetch field. `names` defaults to every computed field of the model.
    """
    instances = [i for i in instances if i.pk is not None]
    if not instances:
        return
    model = type(instances[0])

    stored = computed_fields(model, STORED)
    virtual = computed_fields(model, VIRTUAL)
    if names is None:
        names = list(stored) + list(virtual)
    selected = [get_computed_field(model, name) for name in names]

    read_columns = [f for f in selected if f.stored]
    read_annotations = [f for f in selected if not f.stored and f.annotation_method is not None]
    run_prefetch = [f for f in selected if not f.stored and f.prefetch_method is not None]

    if read_columns or read_annotations:
        rows = (
            model._base_manager
            .filter(pk__in=[i.pk for i in instances])
            .annotate(**{alias_for(f): as_subquery(f) for f in read_annotations})
            .values("pk", *[f.attname for f in read_columns], *[alias_for(f) for f in read_annotations])
        )
        by_pk = {row["pk"]: row for row in rows}
        for instance in instances:
            row = by_pk.get(instance.pk)
            if row is None:
                continue
            for field in read_columns:
                setattr(instance, field.attname, row[field.attname])
            for field in read_annotations:
                instance.__dict__[field.name] = row[alias_for(field)]

    for field in run_prefetch:
        field.run_prefetch(instances)
