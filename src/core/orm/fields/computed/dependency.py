"""What each stored computed field depends on, indexed by the model to watch.

`depends_on` is parsed once, at startup, into `Binding`s: "when these fields of
this watched model change, or when rows of it appear or disappear, this computed
field must be recomputed on these root rows". `RefreshComputedFieldsContext` only
ever asks this registry; nothing here writes.

A dependency is a path of relations, optionally ending on a field:

  "label"                          a local field
  "parent"                         a forward foreign key: reassigning it
  "parent__status"                 a field of the row a foreign key points to
  "lines"                          a reverse foreign key: rows joining or leaving it
  "lines__quantity"                ... and that field changing on them
  "tags"                           a many-to-many, declared here or on the other side
  "tags__name"                     ... and that field changing on the related rows
  "lines__product__category__name" any chain of the above

Every model along the path is watched, each with the lookup leading from it back
to the root: renaming a category, moving a product to another category, giving a
line another product, adding or deleting a line all change which name is read.
The number of relations crossed is capped by the `COMPUTED_FIELD_MAX_HOPS`
setting (4 by default): every hop widens the set of rows a single write can make
stale, and a path longer than that is refused at startup rather than discovered
in production.
"""

import dataclasses
import typing as t
from collections import defaultdict

from django.apps import apps as django_apps
from django.conf import settings
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
    # Among those, the relations that are part of `path` itself -- the way back to
    # the root -- so that writing one moves the row from one root to another.
    # Updating one requires capturing the roots *before* the write as well, since
    # the old root loses the row. A relation leading *away* from the root (the next
    # hop) is a plain trigger: the row reaches the same roots before and after.
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
            parsed = [b for dep in field.depends_on for b in _parse_dependency(model, field, dep)]
            for binding in _merge(parsed):
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


def max_hops() -> int:
    return getattr(settings, "COMPUTED_FIELD_MAX_HOPS", 4)


class _Watch:
    """What one dependency asks of one `(watched model, path)`, while parsing."""

    def __init__(self):
        self.trigger_fields = set()
        self.membership_fields = set()
        self.on_existence = False
        self.fk_attname = None


def _parse_dependency(root, field, dep) -> t.List[Binding]:
    """The bindings `dep` needs, one per watched `(model, path)`, in path order.

    Walks the path one relation at a time. At each hop from `model` to `target`:

    * a forward relation (a foreign key, or a many-to-many declared on `model`) is
      written on `model`: it triggers there, with the path up to `model`. It leads
      away from the root, so it is no membership change.
    * a reverse relation (the key, or the many-to-many, declared on `target`) is
      written on `target`: it triggers there, with the path up to `target`, and it
      *is* a membership change -- it is the way back to the root.
    * rows of `target` appearing or disappearing change what the path reaches.

    A trailing field triggers on the last model reached.
    """
    where = f"depends_on={dep!r} on {root.__name__}.{field.name}"
    parts = dep.split(LOOKUP_SEP)
    watches = {}  # (watched model, path) -> _Watch, insertion-ordered

    def watch(model, path):
        return watches.setdefault((model, LOOKUP_SEP.join(path) or None), _Watch())

    model, path, hops = root, [], 0
    for index, name in enumerate(parts):
        try:
            rel = model._meta.get_field(name)
        except FieldDoesNotExist:
            raise ImproperlyConfigured(f"{where}: '{name}' is not a field of {model.__name__}.")

        if not rel.is_relation:
            if index != len(parts) - 1:
                raise ImproperlyConfigured(f"{where}: '{name}' is not a relation.")
            watch(model, path).trigger_fields |= _field_names(rel)
            break

        hops += 1
        if hops > max_hops():
            raise ImproperlyConfigured(
                f"{where}: crosses more than {max_hops()} relations, the "
                f"COMPUTED_FIELD_MAX_HOPS setting. Every hop widens what a single "
                f"write can make stale."
            )

        target = rel.related_model
        if target is None:
            raise ImproperlyConfigured(f"{where}: '{name}' is a generic relation, not supported.")
        lookup = rel.name  # for a reverse relation, its query name
        if isinstance(rel, models.ForeignObjectRel):
            # Reverse: written on `target`, and the way back to the root.
            own = _field_names(rel.field)
            target_watch = watch(target, path + [lookup])
            target_watch.trigger_fields |= own
            target_watch.membership_fields |= own
            if not path and not rel.many_to_many:
                # First hop over a reverse key: the root pk sits on the instance.
                target_watch.fk_attname = rel.field.attname
        else:
            # Forward: written on `model`, leading away from the root.
            watch(model, path).trigger_fields |= _field_names(rel)

        # Rows of `target` appearing or disappearing change what the path reaches:
        # a reverse relation gains or loses members, a deleted forward target nulls
        # or deletes what pointed to it, a deleted many-to-many target leaves the
        # relation through the `through` table.
        watch(target, path + [lookup]).on_existence = True
        model, path = target, path + [lookup]

    return [
        Binding(
            root_model=root, field=field, watched_model=watched_model, path=watched_path,
            trigger_fields=frozenset(w.trigger_fields),
            membership_fields=frozenset(w.membership_fields),
            on_existence=w.on_existence and watched_path is not None,
            fk_attname=w.fk_attname,
        )
        for (watched_model, watched_path), w in watches.items()
    ]


def _merge(bindings: t.Iterable[Binding]) -> t.List[Binding]:
    """One binding per `(field, watched model, path)`, the union of the others.

    `total` depending on `lines__quantity` and `lines__unit_price` watches `Line`
    through `lines` once, on both fields, rather than twice.
    """
    merged = {}
    for b in bindings:
        key = (b.field, b.watched_model, b.path)
        if key not in merged:
            merged[key] = b
            continue
        m = merged[key]
        merged[key] = dataclasses.replace(
            m,
            trigger_fields=m.trigger_fields | b.trigger_fields,
            membership_fields=m.membership_fields | b.membership_fields,
            on_existence=m.on_existence or b.on_existence,
            fk_attname=m.fk_attname or b.fk_attname,
        )
    return list(merged.values())


def _compute_depths(bindings) -> t.Dict[models.Field, int]:
    """Depth of each stored computed field in the "reads" graph, or a cycle error.

    A field reading *itself* -- on other rows, through relations: `Menu.depth` on
    `parent__depth`, `Order.x` on `lines__order__x` -- is refused too. Refreshing it
    would queue it again on the rows reading those, at the same depth: harmless on a
    tree, endless on rows that point at each other. With it refused, every
    propagation during a flush goes strictly deeper, so a flush always ends.
    """
    reads = defaultdict(set)  # field -> stored computed fields it reads
    fields = set()
    for watched_model, model_bindings in bindings.items():
        stored = computed_fields(watched_model, STORED)
        for binding in model_bindings:
            fields.add(binding.field)
            for name in binding.trigger_fields:
                if name not in stored:
                    continue
                if stored[name] is binding.field:
                    raise ImproperlyConfigured(
                        f"{binding.root_model.__name__}.{binding.field.name} depends on "
                        f"itself through '{binding.path or binding.field.name}': a "
                        f"refresh would trigger itself, without end on rows that "
                        f"point at each other."
                    )
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
