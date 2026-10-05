"""`ComputedField`: one class for both strategies.

`stored=False` (the default) -- a virtual field. Never a column, never a
migration. The value comes from `annotation_method` (through
`with_computed_annotation()`) or from `prefetch_method` (through
`with_computed_prefetch()`), with a lazy per-instance query as the fallback.

`stored=True` -- a real column, with a real migration, kept in sync by
`RefreshComputedFieldsContext`, which the service layer enters around every
write. Its value comes from either method as well. There are no signals and no
`pre_save()`: services write with `bulk_create()` and `queryset.update()`, which
fire neither, so the one write path that matters is the one the services own.
Anything that writes around them -- the admin's `save()`, a raw `update()`, a
data migration -- leaves the column stale until `refresh_computed()` reconciles
it.

Why the class subclasses `models.Field` even when virtual: it shares
`__init__`, `verbose_name` and the rest for free, and the virtual branch of
`contribute_to_class()` deliberately skips `_meta.add_field()`, the one call that
makes django treat a field as a column. Never calling it keeps virtual fields
out of migrations, `ModelForm`, `.values()` and `.only()`.

Why the stored checks live in `check()` and not in `__init__()`: migrations
rebuild the field from `deconstruct()`, which leaves out `annotation_method`,
`prefetch_method` and `depends_on` -- application behaviour, irrelevant to the
schema, and not serializable anyway (a lambda). `__init__` must accept being
called without them during that replay; the checks run against the real,
installed models only.
"""

from django.core import checks
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.db import models
from django.db.models import F, GeneratedField
from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import Subquery
from django.db.models.query import ModelIterable

from .utils import (
    ANNOTATION,
    PREFETCH,
    STORED,
    VIRTUAL,
    alias_for,
    as_subquery,
    computed_fields,
    get_computed_field,
)


class ComputedFieldDescriptor:
    """Non-data descriptor of a virtual field.

    A value loaded by `with_computed_annotation()` / `with_computed_prefetch()`
    lands in the instance `__dict__`, which wins over a non-data descriptor, so this
    only runs when nothing was loaded. It then costs one query per instance and per
    field, and raises `SynchronousOnlyOperation` from a coroutine: it is a
    convenience for sync code (the admin, a shell), never what a route relies on --
    the service layer loads what a response reads.
    """

    def __init__(self, field):
        self.field = field

    def __get__(self, instance, owner=None):
        if instance is None:
            return self.field
        field = self.field
        if instance.pk is None:
            return None

        if field.annotation_method is not None:
            value = (
                type(instance)._base_manager
                .filter(pk=instance.pk)
                .annotate(**{alias_for(field): as_subquery(field)})
                .values_list(alias_for(field), flat=True)
                .first()
            )
            instance.__dict__[field.name] = value
        else:
            field.run_prefetch([instance])
        return instance.__dict__.get(field.name)


def is_row_local(expression) -> bool:
    """Whether `expression` only reads columns of the row itself.

    No aggregate, no subquery, no window, and no `F()` crossing a relation: what
    PostgreSQL can compute as a generated column. Decided on the expression rather
    than on `depends_on`, which cannot tell at declaration time whether `"lines"` or
    `"parent"` is a column or a relation -- the model does not exist yet.
    """
    if isinstance(expression, Subquery):
        return False
    if getattr(expression, "contains_aggregate", False) or getattr(expression, "contains_over_clause", False):
        return False
    if isinstance(expression, F):
        return LOOKUP_SEP not in expression.name
    if not hasattr(expression, "get_source_expressions"):
        return True  # a plain value
    return all(is_row_local(e) for e in expression.get_source_expressions() if e is not None)


class ComputedField(models.Field):
    """A field whose value is derived from other data.

    A stored field whose annotation only reads its own row (`Upper("label")`,
    `F("quantity") * F("unit_price")`) is not a `ComputedField` at all: the
    constructor returns a `GeneratedField` instead, which PostgreSQL recomputes in
    the very statement writing the row -- whatever writes it, the admin and raw SQL
    included, and at no extra query. Nothing would be gained by refreshing it after
    the fact, and every write would pay one more `UPDATE`. Merging that refresh into
    the write itself does not work either: every expression of a SET clause reads
    the row as it was *before* the statement. Dependents of such a field watch its
    inputs instead (see `dependency._field_names`).

    :param output_field: the django field describing the value -- its type, its
        column when stored, its schema type in the API. Required.
    :param annotation_method: a callable returning the expression, written as for
        `.annotate()`: `lambda: Sum(F("lines__quantity") * F("lines__unit_price"))`.
        Wrapped in a correlated subquery wherever it is used (see `as_subquery`).
    :param prefetch_method: for a value only python can compute. Either a callable
        or the name of a model classmethod / staticmethod, taking a list of
        instances and returning `{pk: value}`. A missing pk reads as None.
    :param depends_on: what the value depends on, as lookups from this model:
        `"label"`, `"parent__status"`, `"lines__quantity"`, `"tags__name"`,
        `"lines__product__category__name"`. Required when stored; ignored
        otherwise. A relation path reacts to rows joining or leaving each relation
        on the way, and to its last field changing. At most
        `COMPUTED_FIELD_MAX_HOPS` relations (4 by default), and never the field
        itself on other rows (`parent__depth` for `depth`): both are refused at
        startup. Every write a path watches recomputes every row it leads back to,
        so prefer depending on ids over displayed values: storing the top
        category's id watches `lines__product__category` and ignores renames,
        storing its name recomputes every order reaching it on each rename. A field
        whose reach is unbounded is better left virtual.
    :param stored: whether the value is a column kept in sync.

    Exactly one of `annotation_method` / `prefetch_method`.
    """

    description = "Computed value"

    def __new__(
        cls,
        verbose_name=None,
        output_field=None,
        annotation_method=None,
        prefetch_method=None,
        depends_on=(),
        stored=False,
        **kwargs,
    ):
        if stored and annotation_method is not None and prefetch_method is None:
            try:
                expression = annotation_method() if callable(annotation_method) else annotation_method
            except Exception:  # pylint: disable=broad-except
                # Not evaluable at declaration: typically a lambda naming a model
                # declared further down the module -- the very reason it is a
                # lambda. Whatever it names, it is not its own row, so it stays a
                # computed field; the expression is evaluated again where it is
                # used, where a genuine error surfaces.
                expression = None
            if expression is not None and is_row_local(expression):
                # Not an instance of `cls`, so python does not call `__init__` on it.
                # Nullable like a stored computed field, so both read alike in a
                # schema. Its migration records a `GeneratedField`: a historical
                # model never goes through here again.
                kwargs.setdefault("null", True)
                return GeneratedField(
                    expression=expression,
                    output_field=output_field,
                    db_persist=True,  # PostgreSQL only has stored generated columns
                    verbose_name=verbose_name,
                    **kwargs,
                )
        return super().__new__(cls)

    def __init__(
        self,
        verbose_name=None,
        output_field=None,
        annotation_method=None,
        prefetch_method=None,
        depends_on=(),
        stored=False,
        **kwargs,
    ):
        if not stored:
            # Safe to fail fast: a virtual field is never in `_meta.fields`, so
            # migrations never rebuild it -- and its checks would never run either,
            # django only checks the fields it knows about.
            if (annotation_method is None) == (prefetch_method is None):
                raise ImproperlyConfigured(
                    "A virtual ComputedField needs exactly one of 'annotation_method' "
                    "and 'prefetch_method'."
                )
            if output_field is None:
                raise ImproperlyConfigured("ComputedField requires 'output_field'.")

        self.output_field = output_field
        self.annotation_method = annotation_method
        self.prefetch_method = prefetch_method
        self.depends_on = tuple(depends_on)
        self.stored = stored

        if stored:
            # NULL until the first refresh, and never written by a client.
            kwargs.setdefault("null", True)
            kwargs.setdefault("blank", True)
            kwargs.setdefault("editable", False)

        super().__init__(verbose_name=verbose_name, **kwargs)

    # -----------------------------------------------------------------
    # Checks
    # -----------------------------------------------------------------

    def check_computed(self):
        """Every computed-field specific check, stored or virtual.

        Not `check()`: django only runs that for the fields in `_meta`, which a
        virtual field is not. `check_computed_fields` below calls this for both.
        """
        errors = []
        if self.output_field is None:
            errors.append(checks.Error(
                "ComputedField requires 'output_field'.",
                obj=self, id="computed_field.E001",
            ))
        if (self.annotation_method is None) == (self.prefetch_method is None):
            errors.append(checks.Error(
                "ComputedField requires exactly one of 'annotation_method' and "
                "'prefetch_method'.",
                obj=self, id="computed_field.E002",
            ))
        if self.stored and not self.depends_on:
            errors.append(checks.Error(
                "ComputedField(stored=True) requires 'depends_on': it must know what "
                "to react to in order to keep the column in sync.",
                obj=self, id="computed_field.E003",
            ))
        queryset_class = getattr(self.model._default_manager, "_queryset_class", None)
        if queryset_class is None or not issubclass(queryset_class, ComputedQuerySetMixin):
            errors.append(checks.Error(
                f"{self.model.__name__} declares a ComputedField, so its default "
                "manager must be built on a QuerySet inheriting ComputedQuerySetMixin.",
                obj=self, id="computed_field.E004",
            ))
        return errors

    # -----------------------------------------------------------------
    # Database behaviour, delegated to `output_field`
    # -----------------------------------------------------------------

    def get_internal_type(self):
        if self.output_field is not None:
            return self.output_field.get_internal_type()
        return super().get_internal_type()

    def db_type(self, connection):
        if self.stored and self.output_field is not None:
            return self.output_field.db_type(connection)
        return None

    def get_prep_value(self, value):
        if self.output_field is not None:
            return self.output_field.get_prep_value(value)
        return value

    def get_db_prep_value(self, value, connection, prepared=False):
        if self.output_field is not None:
            return self.output_field.get_db_prep_value(value, connection, prepared=prepared)
        return super().get_db_prep_value(value, connection, prepared=prepared)

    def from_db_value(self, value, expression, connection):
        from_db = getattr(self.output_field, "from_db_value", None)
        if from_db is not None:
            return from_db(value, expression, connection)
        return value

    def to_python(self, value):
        if self.output_field is not None:
            return self.output_field.to_python(value)
        return value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # The public path, as django does for its own fields: the module layout
        # stays free to change without rewriting migrations.
        path = "core.orm.fields.ComputedField"
        if self.stored:
            kwargs["output_field"] = self.output_field
            kwargs["stored"] = True
        # `annotation_method` / `prefetch_method` / `depends_on` are always left
        # out: application behaviour, not schema.
        return name, path, args, kwargs

    # -----------------------------------------------------------------
    # Computation
    # -----------------------------------------------------------------

    def get_annotation(self):
        expr = self.annotation_method
        if expr is None:
            raise ImproperlyConfigured(f"ComputedField '{self.name}' has no annotation_method.")
        return expr() if callable(expr) else expr

    def run_prefetch(self, instances):
        """Compute the value of every given instance with `prefetch_method`, and set it."""
        instances = [i for i in instances if i.pk is not None]
        if not instances:
            return
        method = self.prefetch_method
        if isinstance(method, str):
            method = getattr(self.model, method)
        values = method(instances) or {}
        for instance in instances:
            value = values.get(instance.pk)
            if self.stored:
                setattr(instance, self.attname, value)
            else:
                instance.__dict__[self.name] = value

    # -----------------------------------------------------------------
    # Model registration
    # -----------------------------------------------------------------

    def contribute_to_class(self, cls, name, private_only=False):
        if self.stored:
            super().contribute_to_class(cls, name, private_only=private_only)  # a real column
        else:
            if cls._meta.abstract:
                # Abstract inheritance copies `local_fields` and `private_fields`,
                # and a virtual field is in neither on purpose: it would silently
                # vanish from every child.
                raise ImproperlyConfigured(
                    f"Virtual ComputedField '{name}' cannot be declared on the abstract "
                    f"model {cls.__name__}."
                )
            # Deliberately no `_meta.add_field()`: no column, no migration,
            # invisible to `ModelForm`, `.values()` and `get_fields()`.
            self.set_attributes_from_name(name)
            self.model = cls
            self.column = None
            self.concrete = False
            setattr(cls, name, ComputedFieldDescriptor(self))

        for registry, member in (
            (STORED, self.stored),
            (VIRTUAL, not self.stored),
            (ANNOTATION, self.annotation_method is not None),
            (PREFETCH, self.prefetch_method is not None),
        ):
            if not member:
                continue
            # Set on `_meta` itself, never read through a parent: every model owns
            # its registries, as it owns its `local_fields`.
            if registry not in vars(cls._meta):
                setattr(cls._meta, registry, {})
            getattr(cls._meta, registry)[name] = self


class ComputedQuerySetMixin:
    """QuerySet API of computed fields. Mandatory on the default manager of any model
    declaring one (check `computed_field.E004`).

    A mixin and not a manager, because models already carry their own QuerySet
    (`PageQuerySet`, `MediaQuerySet`...): `class OrderQuerySet(ComputedQuerySetMixin,
    models.QuerySet)`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._computed_prefetch = frozenset()

    def _clone(self):
        clone = super()._clone()
        clone._computed_prefetch = self._computed_prefetch
        return clone

    def _fetch_all(self):
        first_fetch = self._result_cache is None
        super()._fetch_all()
        # Model instances only: after `.values()` there is nothing to set a value on.
        if first_fetch and self._computed_prefetch and self._iterable_class is ModelIterable:
            prefetch_fields = computed_fields(self.model, PREFETCH)
            for name in sorted(self._computed_prefetch):
                prefetch_fields[name].run_prefetch(self._result_cache)

    def with_computed(self, *names):
        """Load the given computed fields, whatever their kind.

        A stored field is a column, already read with the row: nothing to do. A
        virtual one goes through `with_computed_annotation()` or
        `with_computed_prefetch()`, depending on how it is computed.
        """
        qs = self._chain()
        for name in names:
            field = get_computed_field(qs.model, name)
            if field is None:
                raise FieldError(f"'{name}' is not a ComputedField of {qs.model.__name__}")
            if field.stored:
                continue
            if field.annotation_method is not None:
                qs = qs.with_computed_annotation(name)
            else:
                qs = qs.with_computed_prefetch(name)
        return qs

    def with_computed_annotation(self, *names):
        """Virtual fields only: load the values in the same query, as one correlated
        subquery each. Idempotent. Raises `FieldError` for a stored field or an
        unknown name -- a stored field is read as a plain column."""
        qs = self._chain()
        registry = computed_fields(qs.model, ANNOTATION)
        for name in names:
            field = registry.get(name)
            if field is None or field.stored:
                raise FieldError(
                    f"'{name}' is not a virtual ComputedField with an annotation_method "
                    f"on {qs.model.__name__}"
                )
            if name not in qs.query.annotations:
                qs = qs.annotate(**{name: as_subquery(field)})
        return qs

    def with_computed_prefetch(self, *names):
        """Virtual fields only: compute the values with one grouped call per field,
        when the queryset is evaluated. Idempotent."""
        qs = self._chain()
        registry = computed_fields(qs.model, PREFETCH)
        for name in names:
            field = registry.get(name)
            if field is None or field.stored:
                raise FieldError(
                    f"'{name}' is not a virtual ComputedField with a prefetch_method "
                    f"on {qs.model.__name__}"
                )
        qs._computed_prefetch = qs._computed_prefetch | frozenset(names)
        return qs

    def refresh_computed(self, *names):
        """Stored fields only: recompute and persist the given fields (all of them by
        default) on the rows of this queryset, now.

        For the initial backfill after adding a column, or as a reconciliation job
        after writes that went around the service layer. Goes through a
        `RefreshComputedFieldsContext`, so stored fields depending on the refreshed
        ones -- on this model or another -- are refreshed as well, in dependency
        order.
        """
        from .context import RefreshComputedFieldsContext

        registry = computed_fields(self.model, STORED)
        names = names or tuple(registry)
        for name in names:
            if name not in registry:
                raise FieldError(f"'{name}' is not a stored ComputedField on {self.model.__name__}")

        pks = list(self.values_list("pk", flat=True))
        with RefreshComputedFieldsContext() as ctx:
            ctx.refresh(self.model, pks, names)


@checks.register(checks.Tags.models)
def check_computed_fields(app_configs=None, **kwargs):
    from django.apps import apps

    errors = []
    for model in apps.get_models():
        if app_configs is not None and model._meta.app_config not in app_configs:
            continue
        seen = {}
        for registry in (STORED, VIRTUAL):
            seen.update(computed_fields(model, registry))
        for field in seen.values():
            errors.extend(field.check_computed())
    return errors
