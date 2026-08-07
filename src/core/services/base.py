import functools
import typing as t

from django.core import exceptions
from django.db import models
from django.db.utils import DatabaseError
from ninja import FilterSchema
from pydantic import BaseModel

from user.access_policy import Context as AccessContext, apply_access_rules

from .exceptions import ServiceValidationError, ServiceValidationMultiError
from .generics import check_concrete, generic_args_for
from .registry import ServiceRegistry

if t.TYPE_CHECKING:
    from .environment import Environment

ModelT = t.TypeVar("ModelT", bound=models.Model)


class Service:
    """Root of the service layer: what every service holds, model-bound or not."""

    model = None

    def __init__(self, env: "Environment"):
        self.env = env

    def with_context(self, **kwargs) -> "Service":
        """Return the same service on a new environment with the given context values updated."""
        context = dict(self.env.context)
        context.update(kwargs)
        return self.env(context=context).get(self.__class__)

    @functools.cached_property
    def user(self):
        return self.env.user

    @functools.cached_property
    def language(self):
        return self.env.language

    @functools.cached_property
    def tz(self):
        return self.env.tz

    @functools.cached_property
    def context(self):
        return self.env.context


class ServiceBase(Service, t.Generic[ModelT]):
    """A service bound to a django model.

    Owns `ModelT`, because the model is a property of the *service*, not of any
    single operation: each operation mixin owns only its own schema. Declare a
    concrete service as
    `class MyService(CreateMixin[MyCreateSchema], ReadMixin, ServiceBase[MyModel])`.

    Operation mixins call `get_queryset`, `apply_access_rules`, `to_internal_values`,
    `validate_data` and `_database_error_to_validation_error` from here, so they are
    only usable combined with this class.
    """

    model: t.ClassVar[t.Type[models.Model]]

    ValidationError = ServiceValidationError

    def __init_subclass__(cls, **kwargs):
        # Unconditional, and first: python only calls the closest
        # `__init_subclass__` in the MRO, so a missing `super()` call anywhere in
        # the chain silently disables every hook after it. Calling it first also
        # means `cls.model` is set before the operation mixins' own hooks run.
        super().__init_subclass__(**kwargs)

        args = generic_args_for(cls, ServiceBase)
        if args is None or not check_concrete(cls, ServiceBase, args):
            return
        # An explicit declaration on the subclass wins over the deduced one.
        cls.model = cls.__dict__.get("model") or args[0]
        ServiceRegistry.register(cls)

    def get_queryset(self) -> models.QuerySet:
        return self.model.objects.all()

    # -----------------------------------------------------------------
    # Browse
    # -----------------------------------------------------------------

    async def browse(self, pks: t.Iterable) -> models.QuerySet:
        """Records among `pks` that the acting user may read, as an unevaluated queryset.

        The minimal capability a service owes the *other* services, which is why it
        lives here and not in an opt-in mixin: resolving a relation goes through the
        related service's `browse` whatever operations that service chooses to
        expose publicly. `read` is the richer, opt-in surface offered to controllers.

        Deliberately does not raise on missing pks: the caller compares what it
        asked for with what it got. That is what makes "does not exist" and "exists
        but is not visible to you" indistinguishable.

        The returned queryset is *not* evaluated. Access rules are already baked in
        as `Q` objects, so a caller can only narrow it further, never widen it --
        laziness therefore opens no permission hole. Do not consume it from a
        coroutine: any iteration, `len()` or `bool()` would raise
        `SynchronousOnlyOperation`.
        """
        queryset = await self.apply_access_rules(self.get_queryset(), "read")
        return queryset.filter(pk__in=pks)

    # -----------------------------------------------------------------
    # Utils
    # -----------------------------------------------------------------

    def _input_values(
        self, data: BaseModel, schema: t.Type[BaseModel], exclude_unset: bool
    ) -> t.Dict:
        """Turn a validated input schema into a dict of ORM values.

        Raw dicts are refused. Levels 1 and 2 -- types, coercion, `choices`, lengths,
        validators -- are guaranteed by *building* the schema, so accepting a dict
        here would reopen the hole this layer exists to close, and it would only be
        closed on the HTTP path where ninja happens to validate first.

        Values are extracted according to the *service's* declared schema, never
        `type(data)`. A caller may legitimately hold a narrower schema over the same
        model -- `profile_update` passes a profile schema to `update` -- and a field
        the service does not accept must not slip through because the caller's schema
        happened to carry it.
        """
        if not isinstance(data, BaseModel):
            raise TypeError(
                f"{type(self).__name__} expects a {schema.__name__} instance, "
                f"got {type(data).__name__}. Build the schema so its validation runs."
            )

        declared = schema.model_fields.keys()
        names = (data.model_fields_set & declared) if exclude_unset else declared
        return {name: getattr(data, name) for name in names if hasattr(data, name)}

    async def apply_access_rules(self, queryset: models.QuerySet, operation: str):
        # Roles come from the environment, which fetches them at most once per unit
        # of work: rules are applied on every operation, and once relations are
        # resolved through the related service each relation would otherwise cost
        # an extra role query.
        context = AccessContext(user=self.env.user, roles=await self.env.get_access_roles())
        return await apply_access_rules(queryset, operation, context)

    def to_internal_values(
        self, data: t.List[BaseModel], exclude_unset: bool = False
    ) -> t.List[t.Dict]:
        # convert input in list of dict
        error = ServiceValidationMultiError({}, code="invalid_data")
        data_list = []
        for index, item in enumerate(data):
            if isinstance(item, dict):
                suberror = ServiceValidationError({})
                for key, val in item.items():
                    try:
                        field = self.model._meta.get_field(key)
                        field.run_validators(val)
                    except exceptions.ValidationError as exc:
                        suberror.add_message(
                            str(exc),
                            key=key,
                        )
                data_list.append(item)
                if suberror:
                    error.add_error(index, suberror)
            else:
                raise TypeError(f"Invalid data type: {type(item)}. Expected dict.")

        # raise all error at once
        if error:
            raise error

        # extract relational field names
        many_to_many_fields = []
        foreign_key_fields = []
        for field in self.model._meta.get_fields():
            if isinstance(field, models.ForeignKey):
                foreign_key_fields.append(field.name)
            if isinstance(field, models.ManyToManyField):
                many_to_many_fields.append(field.name)

        # group all values of relational fields
        many_to_many = {}  # fname -> set of values
        foreign_key = {}  # fname -> set of values
        for item in data_list:
            fields = set(item.keys())

            for fk_fname in set(foreign_key_fields) & fields:
                foreign_key.setdefault(fk_fname, set())
                fval = item.get(fk_fname)
                if fval is not None:
                    foreign_key[fk_fname] |= set([fval])

            for m2m_fname in set(many_to_many_fields) & fields:
                many_to_many.setdefault(m2m_fname, set())
                many_to_many[m2m_fname] |= set(item.get(m2m_fname) or [])

        # fetch relations to minimize the number of queries.
        # TODO (step 5): go through `env[related_model].browse()` so that relations
        # are resolved with the acting user's access rules instead of bypassing them.
        many_to_many_instances = {}
        for fname, values in many_to_many.items():
            field = self.model._meta.get_field(fname)
            related_model = field.related_model
            related_instances = related_model.objects.filter(pk__in=values)
            many_to_many_instances[fname] = {
                instance.pk: instance for instance in related_instances
            }

        foreign_key_instances = {}
        for fname, values in foreign_key.items():
            field = self.model._meta.get_field(fname)
            related_model = field.related_model
            related_instances = related_model.objects.filter(pk__in=values)
            foreign_key_instances[fname] = {
                instance.pk: instance for instance in related_instances
            }

        # convert data to internal values, replacing relational fields values with the corresponding instances.
        result = []
        error = ServiceValidationMultiError({}, code="invalid_data")
        for index, item in enumerate(data_list):
            fields = set(item.keys())

            values = {}
            for fname in fields:
                suberror = ServiceValidationError({})

                fval = item.get(fname)

                if fname in many_to_many_instances:
                    invalid_values = []
                    valid_values = []
                    for v in fval or []:
                        if v not in many_to_many_instances[fname]:
                            invalid_values.append(v)
                        else:
                            valid_values.append(many_to_many_instances[fname][v])
                    values[fname] = valid_values

                    if invalid_values:
                        suberror.add_message(
                            f"Invalid value(s) for field '{fname}': {','.join(invalid_values)}",
                            key=fname,
                        )

                elif fname in foreign_key_instances:
                    if fval not in foreign_key_instances[fname]:
                        suberror.add_message(
                            f"Invalid value for field '{fname}': {fval}",
                            key=fname,
                        )
                    else:
                        values[fname] = foreign_key_instances[fname].get(fval)

                else:
                    values[fname] = fval

                if suberror:
                    error.add_error(index, suberror)

            result.append(values)

        # raise all error at once
        if error:
            raise error

        return result

    def validate_data(self, data: t.Dict, instance: models.Model) -> None:
        """Business rules that need current state, the level no schema can cover.

        Called once per record, with the instance being updated (None on creation).
        Raise `ServiceValidationError` to reject; return nothing.
        """

    def _apply_filters(
        self,
        queryset: models.QuerySet,
        filters: t.Union[BaseModel, FilterSchema, t.Dict],
    ) -> models.QuerySet:
        if isinstance(filters, FilterSchema):
            return filters.filter(queryset)
        elif isinstance(filters, BaseModel):
            return queryset.filter(**filters.model_dump(exclude_unset=True))
        elif isinstance(filters, dict):
            return queryset.filter(**filters)
        return queryset

    def _database_error_to_validation_error(self, exc: DatabaseError):
        error_message = str(exc)

        errors = []
        for constraint in self.model._meta.constraints:
            if constraint.name in error_message:
                violation_error_message = getattr(constraint, 'violation_error_message', None)
                if violation_error_message:
                    errors.append(violation_error_message)
                    break # if we found the violated constraint, we can stop checking the others

        if not errors:
            errors.append("A global validation error occurred: " + error_message)

        return ServiceValidationMultiError({"__all__": ServiceValidationError(errors)}, code="integrity_error")
