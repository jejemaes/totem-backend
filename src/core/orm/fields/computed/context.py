"""Batch the refresh of stored computed fields over a unit of work.

Every write declares what it did -- `created()`, `modified()`, `deleted()` -- and
the context only records which stored fields became stale on which root rows. The
recomputation runs once, when the outermost `with` exits, as the minimum number of
`UPDATE` statements: one per model and per dependency depth, however many rows,
fields or individual writes were involved.

There are no signals behind this: the service layer writes with `bulk_create()`
and `queryset.update()`, which fire none, and enters a context around each write
(see `Environment.computed_refresh()`).
"""

import typing as t
from collections import defaultdict

from django.db import models, router
from django.db.models.deletion import Collector
from django.db.models.query import QuerySet

from .dependency import bindings_for, get_registry
from .utils import STORED, bulk_refresh_fields, computed_fields


class RefreshComputedFieldsContext:
    """Re-entrant: an inner `with` on the same instance joins the outer one, and only
    the outermost exit flushes. That is what lets a service called from another
    service's postprocess share its parent's unit of work instead of refreshing on
    its own, half-way through.

    If the outermost block raises, nothing is refreshed and the pending work is
    dropped: the enclosing transaction is rolling back anyway. An exception that an
    outer block catches does not drop anything -- recomputing a row whose write was
    rolled back is harmless, missing one is not.
    """

    def __init__(self):
        self._pending = defaultdict(set)  # stored computed field -> {root pk, ...}
        self._depth = 0

    def __enter__(self):
        self._depth += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        self._depth -= 1
        if self._depth == 0:
            if exc_type is None:
                self.flush()
            else:
                self._pending.clear()
        return False

    # -----------------------------------------------------------------
    # What the writes declare
    # -----------------------------------------------------------------

    def created(self, instances: t.Iterable[models.Model]) -> None:
        """Rows were just inserted (`bulk_create`), relations included.

        Call it *after* the many-to-many relations of the new rows are written: a
        model watching them through its side of a many-to-many finds its roots
        through the `through` table.

        Every stored field of the new rows is stale, whatever it depends on -- the
        column is NULL. And every root watching this model for existence is stale.
        """
        instances = [i for i in instances if i.pk is not None]
        if not instances:
            return
        model = type(instances[0])
        pks = [i.pk for i in instances]

        for field in computed_fields(model, STORED).values():
            self._pending[field].update(pks)

        for binding in bindings_for(model):
            if binding.on_existence and not binding.is_local:
                self._add(binding, self._roots(binding, pks, instances))

    def modified(
        self,
        model: t.Type[models.Model],
        pks: t.Iterable,
        update_fields: t.Iterable[str],
        before: bool = False,
    ) -> None:
        """Rows `pks` of `model` had `update_fields` written, many-to-many included.

        Call it *after* the write. When `has_relation_to_modify()` says so, call it
        *before* the write too, with `before=True`: a reassigned foreign key or a
        rewritten many-to-many takes the rows away from roots that the after-call can
        no longer find. `before=True` only resolves those membership dependencies, so
        it costs nothing when only plain values change.
        """
        pks = list(pks)
        update_fields = set(update_fields)
        if not pks or not update_fields:
            return
        # Several fields of one root model often watch through the same relation
        # (`Order.total` and `Order.total_of_amounts`, both through `lines`): the
        # roots are the same, resolve them once.
        roots = {}
        for binding in bindings_for(model):
            if not binding.trigger_fields & update_fields:
                continue
            if before and not binding.membership_fields & update_fields:
                continue
            key = (binding.root_model, binding.path)
            if key not in roots:
                roots[key] = self._roots(binding, pks)
            self._add(binding, roots[key])

    def deleted(self, queryset: QuerySet) -> None:
        """The rows of `queryset` are about to be deleted. Call it *before* the delete:
        once they are gone, nothing leads back to their roots.

        When the deletion can cascade to a watched model (known statically), the
        cascade is collected up front -- the same collection django is about to make
        -- so the rows deleted or nulled through `on_delete` count too.
        """
        model = queryset.model
        cascades = get_registry().cascades.get(model)
        if not cascades and not any(b.on_existence and not b.is_local for b in bindings_for(model)):
            return  # nothing watches these rows: not even their pks are read
        pks = list(queryset.values_list("pk", flat=True))
        if not pks:
            return
        self._existence_changed(model, pks)

        if not cascades:
            return
        collector = Collector(using=queryset.db or router.db_for_write(model), origin=queryset)
        collector.collect(model._base_manager.filter(pk__in=pks))
        for related_model, instances in collector.data.items():
            if related_model in cascades:
                # The rows asked for are already counted; a self-referencing
                # cascade (a tree) adds more rows of the same model.
                cascaded = {i.pk for i in instances} - (set(pks) if related_model is model else set())
                self._existence_changed(related_model, list(cascaded))
        for fast_delete in collector.fast_deletes:
            if fast_delete.model in cascades:
                self._existence_changed(
                    fast_delete.model, list(fast_delete.values_list("pk", flat=True))
                )
        for (field, _value), batches in collector.field_updates.items():
            if field.model not in cascades:
                continue
            updated = []
            for batch in batches:
                if isinstance(batch, QuerySet):
                    updated.extend(batch.values_list("pk", flat=True))
                else:
                    updated.extend(obj.pk for obj in batch)
            self.modified(field.model, updated, {field.name}, before=True)

    def has_relation_to_modify(self, model: t.Type[models.Model], update_fields: t.Iterable[str]) -> bool:
        """Whether writing `update_fields` on `model` can move rows between roots -- if
        so, `modified(before=True)` must run before the write. No query."""
        update_fields = set(update_fields)
        return any(b.membership_fields & update_fields for b in bindings_for(model))

    def refresh(self, model: t.Type[models.Model], pks: t.Iterable, names: t.Iterable[str]) -> None:
        """Mark stored fields `names` of rows `pks` as stale, explicitly."""
        stored = computed_fields(model, STORED)
        pks = list(pks)
        for name in names:
            self._pending[stored[name]].update(pks)

    # -----------------------------------------------------------------
    # Flush
    # -----------------------------------------------------------------

    def flush(self) -> None:
        """Recompute everything pending, in dependency order.

        Fields are refreshed by increasing depth: a stored field is refreshed after
        every stored field it reads. Refreshing a field is itself a write that
        dependents watch, so it is fed back through `modified()`, which can only
        queue deeper fields. Within one depth, the fields of a model share one
        `UPDATE` on the union of their rows: recomputing a row whose inputs did not
        change is correct, only one statement more per field would not be.
        """
        depth = get_registry().depth
        while self._pending:
            level = min(depth.get(field, 0) for field in self._pending)
            batch = defaultdict(lambda: (set(), set()))  # model -> (fields, pks)
            for field in [f for f in self._pending if depth.get(f, 0) == level]:
                fields, pks = batch[field.model]
                fields.add(field)
                pks |= self._pending.pop(field)

            for model, (fields, pks) in batch.items():
                bulk_refresh_fields(model, pks, fields)
                self.modified(model, pks, {f.name for f in fields})

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _add(self, binding, root_pks) -> None:
        root_pks = {pk for pk in root_pks if pk is not None}
        if root_pks:
            self._pending[binding.field].update(root_pks)

    def _existence_changed(self, model, pks) -> None:
        for binding in bindings_for(model):
            if binding.on_existence and not binding.is_local:
                self._add(binding, self._roots(binding, pks))

    @staticmethod
    def _roots(binding, pks, instances=None) -> t.Set:
        if binding.is_local:
            return set(pks)
        if instances is not None and binding.fk_attname:
            return {getattr(i, binding.fk_attname, None) for i in instances}
        return set(
            binding.root_model._base_manager
            .filter(**{f"{binding.path}__in": list(pks)})
            .order_by()  # a `Meta.ordering` would defeat the DISTINCT
            .values_list("pk", flat=True)
            .distinct()
        )


def refresh_computed_for_created(instances: t.Iterable[models.Model]) -> None:
    """For a `bulk_create()` made outside the service layer: refresh what the new
    rows made stale -- their own stored fields and the roots watching them."""
    with RefreshComputedFieldsContext() as ctx:
        ctx.created(instances)
