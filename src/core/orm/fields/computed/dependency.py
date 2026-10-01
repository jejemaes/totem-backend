"""What each stored computed field depends on, indexed by the model to watch.

`depends_on` is parsed once, at startup, into `Binding`s: "when these fields of
this watched model change, or when rows of it appear or disappear, this computed
field must be recomputed on these root rows". `RefreshComputedFieldsContext` only
ever asks this registry; nothing here writes.

Supported shapes, two segments at most -- anything longer is refused at startup
rather than silently not watched:

  "label"               a local field
  "parent"              a forward foreign key: reassigning it
  "parent__status"      a field of the row a foreign key points to
  "lines"               a reverse foreign key: rows joining or leaving it
  "lines__quantity"     ... and that field changing on them
  "tags"                a many-to-many, declared here or on the other side
  "tags__name"          ... and that field changing on the related rows
"""

import dataclasses
import typing as t
from collections import defaultdict

from django.apps import apps as django_apps
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models.constants import LOOKUP_SEP

from .utils import STORED, computed_fields


@dataclasses.dataclass(frozen=True)
class Binding:
    # The model owning the stored computed field, and the field itself.
    root_model: t.Type[models.Model]
    field: models.Field
    # The model whose writes may change the value.
    watched_model: t.Type[models.Model]
    # Lookup from the root model to the watched one: root rows affected by watched
    # rows `pks` are `root_model.filter(<path>__in=pks)`. None when the watched
    # model *is* the root (a local dependency): the root rows are the written rows.
    path: t.Optional[str]
    # Fields of the watched model whose update triggers a refresh, by name and by
    # attname, since a service writes `order` and a queryset may write `order_id`.
    trigger_fields: t.FrozenSet[str]
    # Among those, the ones that move a row from one root to another (a foreign key
    # or a many-to-many). Updating one requires capturing the roots *before* the
    # write as well, since the old root loses the row.
    membership_fields: t.FrozenSet[str]
    # Whether creating or deleting watched rows changes the value.
    on_existence: bool
    # For a reverse foreign key, the attname of that key on the watched model: the
    # root pk is read straight from an instance, no query needed.
    fk_attname: t.Optional[str] = None

    @property
    def is_local(self) -> bool:
        return self.path is None


@dataclasses.dataclass
class _Registry:
    bindings: t.Dict[t.Type[models.Model], t.List[Binding]]
    # Stored computed field -> depth in the dependency graph. A field is always
    # deeper than every stored computed field it reads, so refreshing by
    # increasing depth never reads a stale input.
    depth: t.Dict[models.Field, int]
    # Model -> the watched models a deletion of its rows can cascade to.
    cascades: t.Dict[t.Type[models.Model], t.FrozenSet[t.Type[models.Model]]]


_registry: t.Optional[_Registry] = None


def get_registry() -> _Registry:
    if _registry is None:
        build_computed_field_dependency_registry()
    return _registry


def bindings_for(model) -> t.List[Binding]:
    return get_registry().bindings.get(model, [])


def build_computed_field_dependency_registry() -> _Registry:
    """Parse every stored computed field of every installed model.

    Called from `CoreConfig.ready()`, so a malformed `depends_on` fails every
    management command at startup instead of a write at runtime. Idempotent: it
    rebuilds from scratch each time.
    """
    global _registry

    bindings = defaultdict(list)
    for model in django_apps.get_models():
        for field in computed_fields(model, STORED).values():
            for dep in field.depends_on:
                for binding in _parse_dependency(model, field, dep):
                    bindings[binding.watched_model].append(binding)

    bindings = dict(bindings)
    _registry = _Registry(
        bindings=bindings,
        depth=_compute_depths(bindings),
        cascades=_compute_cascades(set(bindings)),
    )
    return _registry


def _field_names(field) -> t.Set[str]:
    """The names under which a write of `field` shows up in `update_fields`.

    A `GeneratedField` is never written -- PostgreSQL recomputes it from its inputs
    in the statement writing them -- so a dependency on it is a dependency on those
    inputs. One level is enough: a generated column cannot read another one.
    """
    names = {field.name}
    attname = getattr(field, "attname", None)
    if attname:
        names.add(attname)
    if isinstance(field, models.GeneratedField):
        names |= _referenced_names(field.expression)
    return names


def _referenced_names(expression) -> t.Set[str]:
    if isinstance(expression, models.F):
        return {expression.name}
    names = set()
    for source in getattr(expression, "get_source_expressions", lambda: [])():
        if source is not None:
            names |= _referenced_names(source)
    return names


def _parse_dependency(root, field, dep) -> t.Iterator[Binding]:
    where = f"depends_on={dep!r} on {root.__name__}.{field.name}"
    parts = dep.split(LOOKUP_SEP)
    if len(parts) > 2:
        raise ImproperlyConfigured(
            f"{where}: paths of more than two segments are not supported."
        )
    try:
        rel = root._meta.get_field(parts[0])
    except FieldDoesNotExist:
        raise ImproperlyConfigured(f"{where}: '{parts[0]}' is not a field of {root.__name__}.")

    def local(names, membership=frozenset()):
        return Binding(
            root_model=root, field=field, watched_model=root, path=None,
            trigger_fields=frozenset(names), membership_fields=frozenset(membership),
            on_existence=False,
        )

    if not rel.is_relation:
        if len(parts) == 2:
            raise ImproperlyConfigured(f"{where}: '{parts[0]}' is not a relation.")
        yield local(_field_names(rel))
        return

    target = rel.related_model
    sub_names, sub_membership = set(), set()
    if len(parts) == 2:
        try:
            sub = target._meta.get_field(parts[1])
        except FieldDoesNotExist:
            raise ImproperlyConfigured(f"{where}: '{parts[1]}' is not a field of {target.__name__}.")
        if sub.auto_created and not sub.concrete:
            raise ImproperlyConfigured(
                f"{where}: '{parts[1]}' is a reverse relation of {target.__name__}, "
                f"which would be a third hop."
            )
        sub_names = _field_names(sub)
        if sub.is_relation:
            sub_membership = set(sub_names)

    if rel.concrete and (rel.many_to_one or rel.one_to_one):
        # Forward foreign key: reassigning it changes the value of this very row...
        own = _field_names(rel)
        yield local(own, membership=own)
        if len(parts) == 2:
            # ... and so does that field changing on the row it points to.
            yield Binding(
                root_model=root, field=field, watched_model=target, path=rel.name,
                trigger_fields=frozenset(sub_names),
                membership_fields=frozenset(sub_membership),
                # A deleted target sets the key to NULL, or deletes the root.
                on_existence=True,
            )
    elif rel.one_to_many or rel.one_to_one:
        # Reverse foreign key: the key lives on the watched model, so moving a row to
        # another root is an update of that key.
        fk_names = _field_names(rel.field)
        yield Binding(
            root_model=root, field=field, watched_model=target, path=rel.name,
            trigger_fields=frozenset(fk_names | sub_names),
            membership_fields=frozenset(fk_names | sub_membership),
            on_existence=True,
            fk_attname=rel.field.attname,
        )
    elif rel.many_to_many:
        if rel.concrete:
            # Declared here: the root's own service writes the relation.
            yield local({rel.name}, membership={rel.name})
            yield Binding(
                root_model=root, field=field, watched_model=target, path=rel.name,
                trigger_fields=frozenset(sub_names),
                membership_fields=frozenset(sub_membership),
                # A deleted target leaves the relation through the `through` table.
                on_existence=True,
            )
        else:
            # Declared on the other side: that model's service writes the relation.
            m2m_names = {rel.field.name}
            yield Binding(
                root_model=root, field=field, watched_model=target, path=rel.name,
                trigger_fields=frozenset(m2m_names | sub_names),
                membership_fields=frozenset(m2m_names | sub_membership),
                on_existence=True,
            )
    else:  # pragma: no cover - generic relations
        raise ImproperlyConfigured(f"{where}: unsupported relation type.")


def _compute_depths(bindings) -> t.Dict[models.Field, int]:
    """Depth of each stored computed field in the "reads" graph, or a cycle error."""
    reads = defaultdict(set)  # field -> stored computed fields it reads
    fields = set()
    for watched_model, model_bindings in bindings.items():
        stored = computed_fields(watched_model, STORED)
        for binding in model_bindings:
            fields.add(binding.field)
            for name in binding.trigger_fields:
                if name in stored and stored[name] is not binding.field:
                    reads[binding.field].add(stored[name])
                    fields.add(stored[name])

    depth = {}
    visiting = set()

    def visit(field):
        if field in depth:
            return depth[field]
        if field in visiting:
            raise ImproperlyConfigured(
                f"Stored computed fields depend on each other in a cycle, through "
                f"{field.model.__name__}.{field.name}."
            )
        visiting.add(field)
        depth[field] = 1 + max((visit(dep) for dep in reads[field]), default=-1)
        visiting.discard(field)
        return depth[field]

    for field in fields:
        visit(field)
    return depth


_CASCADING = (models.CASCADE, models.SET_NULL, models.SET_DEFAULT)


def _compute_cascades(watched_models) -> t.Dict[t.Type[models.Model], t.FrozenSet]:
    """For each model, the watched models a deletion can reach through `on_delete`.

    Static, so that a deletion pays for collecting its cascade up front only when it
    can actually reach a watched model -- the common case pays nothing.
    """
    def reachable(model, seen):
        for rel in model._meta.related_objects:
            if not (rel.one_to_many or rel.one_to_one):
                continue
            on_delete = getattr(rel, "on_delete", None)
            if on_delete not in _CASCADING and not getattr(on_delete, "deconstruct", None):
                continue  # PROTECT / RESTRICT / DO_NOTHING: nothing changes
            related = rel.related_model
            if related in seen:
                continue
            seen.add(related)
            if on_delete is models.CASCADE:
                reachable(related, seen)
        return seen

    cascades = {}
    for model in django_apps.get_models():
        reached = frozenset(reachable(model, set()) & watched_models)
        if reached:
            cascades[model] = reached
    return cascades


def computed_fields_to_refresh(instance, changed_fields=None, created=False):
    """Given one written instance, which stored fields need recomputing, on which rows.

    For code that writes a single instance around the service layer -- a `save()` --
    and wants to know what it made stale. `changed_fields=None` means unknown: every
    dependency on the model is assumed touched. `created=True` (or a deletion,
    which should be passed as such) triggers existence dependencies as well.

    Returns `{(root_model, root_pk): {field_name, ...}}`. One query per relation
    dependency whose root cannot be read off the instance itself.
    """
    model = type(instance)
    changed = None if changed_fields is None else set(changed_fields)
    result = defaultdict(set)

    if created:
        for name in computed_fields(model, STORED):
            result[(model, instance.pk)].add(name)

    for binding in bindings_for(model):
        if binding.is_local:
            if created or changed is None or binding.trigger_fields & changed:
                result[(model, instance.pk)].add(binding.field.name)
            continue
        if not (
            (created and binding.on_existence)
            or changed is None
            or binding.trigger_fields & changed
        ):
            continue
        if binding.fk_attname:
            root_pks = [getattr(instance, binding.fk_attname, None)]
        else:
            root_pks = binding.root_model._base_manager.filter(
                **{f"{binding.path}__in": [instance.pk]}
            ).values_list("pk", flat=True)
        for root_pk in root_pks:
            if root_pk is not None:
                result[(binding.root_model, root_pk)].add(binding.field.name)

    return dict(result)
