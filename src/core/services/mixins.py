"""Operation mixins, each owning the schema of the operation it provides.

The public surface is async, but every write runs its transactional body in a
single sync hop. `transaction.atomic` cannot be entered from a coroutine under
Django 5.0 (`connect`, `cursor`, `commit`, `savepoint` are all `@async_unsafe`,
and there is no `aatomic`), and the write path sends `user_change_rights`, whose
receivers query the database synchronously. So each write reads what it needs in
the async phase -- access rules, and later relation resolution -- then hands a
plain sync body to `sync_to_async`. One boundary per unit of work, and
`transaction.atomic` keeps working unchanged inside it.

`thread_sensitive=True` is required: it keeps the body on the calling thread, so
it shares the connection and the enclosing test transaction, which is also what
keeps `assertNumQueries` meaningful.
"""

import typing as t

from asgiref.sync import sync_to_async
from django.core import exceptions
from django.db import models, transaction
from django.db.models import ManyToManyField
from django.db.utils import DatabaseError
from ninja import FilterSchema
from pydantic import BaseModel

from core.orm.queryset import queryset_fetch_fields, queryset_order_by_fields

from .exceptions import ServiceValidationError, ServiceValidationMultiError
from .generics import check_concrete, generic_args_for

CreateT = t.TypeVar("CreateT", bound=BaseModel)
UpdateT = t.TypeVar("UpdateT", bound=BaseModel)


class CreateMixin(t.Generic[CreateT]):
    """Provides `create`. Owns `CreateT`, the input schema of a creation."""

    create_schema: t.ClassVar[t.Type[BaseModel]]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)  # unconditional, see module docstring of base
        args = generic_args_for(cls, CreateMixin)
        if args is None or not check_concrete(cls, CreateMixin, args):
            return
        # An explicit declaration on the subclass wins over the deduced one.
        cls.create_schema = cls.__dict__.get("create_schema") or args[0]

    async def create(self, data: t.List[dict]) -> t.List[models.Model]:
        scoped_queryset = await self.apply_access_rules(self.get_queryset(), "create")
        return await sync_to_async(self._create_atomic, thread_sensitive=True)(
            data, scoped_queryset
        )

    def _create_atomic(
        self, data: t.List[dict], scoped_queryset: models.QuerySet
    ) -> t.List[models.Model]:
        with transaction.atomic():
            queryset = self.get_queryset()

            # Validate data
            error = ServiceValidationMultiError({}, code="creation_invalid_data")
            internal_data = self.to_internal_values(data)
            for index, internal_values in enumerate(internal_data):
                try:
                    self.validate_data(internal_values, None)
                except ServiceValidationError as exc:
                    error.add_error(index, exc)

            if error:
                raise error

            # Remove many-to-many relationships from validated_data.
            # They are not valid arguments to the default `.create()` method,
            # as they require that the instance has already been saved.
            many_to_many_fields = [
                field.name
                for field in queryset.model._meta.get_fields()
                if isinstance(field, ManyToManyField)
            ]
            many_to_many_data = []
            for internal_values in internal_data:
                many_to_many = {}
                for field_name in many_to_many_fields:
                    if field_name in internal_values:
                        many_to_many[field_name] = internal_values.pop(field_name)
                many_to_many_data.append(many_to_many)

            # Create instances
            instances = [self.model(**values) for values in internal_data]  # pylint: disable=not-callable
            try:
                instances = queryset.bulk_create(instances)
            except TypeError as exc:
                raise TypeError(str(exc))
            except DatabaseError as exc:
                raise self._database_error_to_validation_error(exc) from exc

            # Access rules check
            if scoped_queryset.filter(pk__in=[obj.pk for obj in instances]).count() != len(instances):
                raise exceptions.PermissionDenied("You do not have permission to create some of the objects.")

            # Save many-to-many relationships after the instance is created, and set it in the prefetch cache
            for instance, many_to_many_values in zip(instances, many_to_many_data):
                prefetched_objects = getattr(instance, "_prefetched_objects_cache", {})
                for field_name in many_to_many_fields:
                    value = many_to_many_values.get(field_name, [])
                    if value:
                        # optimization: `set` would cause a read, but we are creating
                        # so there is no existing relation.
                        try:
                            getattr(instance, field_name).add(*value)
                        except DatabaseError as exc:
                            raise self._database_error_to_validation_error(exc) from exc
                    # Prime the cache for *every* relation, not only the ones given:
                    # right after a creation a relation nobody set is necessarily
                    # empty. This is what lets an async route serialize the instance
                    # without hitting the database, since ninja serializes outside of
                    # any `sync_to_async`.
                    prefetched_objects[field_name] = value
                setattr(instance, "_prefetched_objects_cache", prefetched_objects)

            # Postprocess
            instances = self._create_postprocess(instances)

        return instances

    def _create_postprocess(self, instances: t.List[models.Model]):
        """This is part of the atomic process of creation. Any error here will rollback the create.
        Override this method to add additional atomic operation.
        """
        return instances


class ReadMixin:
    """Provides `read`, the rich read surface offered to controllers.

    Distinct from `browse` on the base class, which is the minimal by-pk capability
    every service owes the others. A service may expose no `read` at all and still
    be usable as the target of a relation.
    """

    # Configuration
    ordering_fields_nulls_last = "__all__"  # list of orm field names that should be ordered with nulls last, or '__all__' to apply to all fields.

    async def read(
        self,
        filters: t.Union[BaseModel, FilterSchema, t.Dict] = None,
        ordering=None,
        fields: t.List[str] = None,
    ) -> models.QuerySet:
        """ Read records from the database applying access rules, filters, pagination, ordering and fields selection.
            :param filters: either
                - a pydantic model with the filter fields defined, the model_dump of the pydantic model will be used as kwargs for filtering the queryset
                - a ninja FilterSchema instance, the `filter` method of the FilterSchema will be used to filter the queryset
                - a dict with the filter fields and values, the dict will be used as lookups for filtering the queryset
            :param ordering: list of fields to order by, should be a subset of the model fields
            :param fields: list of fields to select (model field name or relational lookup `my_fk_field__field_on_relation`),
                should be a subset of the model fields.

            Note: as pagination alters the result format, it can not be handled here.
            The returned queryset is not evaluated; see `browse` about consuming it
            from a coroutine.
        """
        queryset = self.get_queryset()
        # apply access rules
        queryset = await self.apply_access_rules(queryset, "read")
        # apply filters
        if filters:
            queryset = self._apply_filters(queryset, filters)
        # apply ordering
        if ordering:
            queryset = self._read_apply_ordering(queryset, ordering)
        # apply fields selection
        if fields:
            queryset = self._read_apply_fields(queryset, fields)
        return queryset

    def _read_apply_fields(self, queryset: models.QuerySet, field_lookups: t.List[str]) -> models.QuerySet:
        return queryset_fetch_fields(queryset, field_lookups)

    def _read_apply_ordering(self, queryset: models.QuerySet, ordering_fields: t.List[str]) -> models.QuerySet:
        return queryset_order_by_fields(
            queryset,
            ordering_fields,
            add_pk=True,
            null_last_fields=self.ordering_fields_nulls_last,
        )


class UpdateMixin(t.Generic[UpdateT]):
    """Provides `update`. Owns `UpdateT`, the input schema of an update."""

    update_schema: t.ClassVar[t.Type[BaseModel]]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        args = generic_args_for(cls, UpdateMixin)
        if args is None or not check_concrete(cls, UpdateMixin, args):
            return
        cls.update_schema = cls.__dict__.get("update_schema") or args[0]

    async def update(
        self, filters: BaseModel, data: dict
    ) -> t.Tuple[int, models.QuerySet]:
        """ Update every record matching `filters` with the same data.

        Only the keys present in `data` are written. That matters beyond query
        counts: `UserQuerySet.update` emits `user_change_rights` when `user_type` is
        part of the payload, which invalidates the user's tokens.
        """
        scoped_queryset = await self.apply_access_rules(self.get_queryset(), "update")
        return await sync_to_async(self._update_atomic, thread_sensitive=True)(
            scoped_queryset, filters, data
        )

    def _update_atomic(
        self, scoped_queryset: models.QuerySet, filters: BaseModel, data: dict
    ) -> t.Tuple[int, models.QuerySet]:
        pks = []
        with transaction.atomic():
            queryset = scoped_queryset

            # Apply filters
            if filters:
                queryset = self._apply_filters(queryset, filters)

            # Preprocess data
            internal_values = self.to_internal_values([data])[0]
            update_fields = set(internal_values.keys())

            # Preprocess queryset to optimize which field to fetch
            queryset = self._update_preprocess(queryset, update_fields)
            instances = queryset.all()

            # Validate data with current instances
            error = ServiceValidationMultiError({}, code="update_invalid_data")
            for instance in instances:
                pks.append(instance.pk)
                try:
                    self.validate_data(internal_values, instance)
                except ServiceValidationError as exc:
                    error.add_error(instance.pk, exc)

            if error:
                raise error

            # If no instance found, return now.
            if not pks:
                return 0, queryset.none()

            # Remove many-to-many relationships from internal_values.
            # They are not valid arguments to the default `.update()` method.
            many_to_many = {}
            for field in queryset.model._meta.get_fields():
                if (
                    isinstance(field, ManyToManyField)
                    and field.name in internal_values
                ):
                    many_to_many[field.name] = internal_values.pop(field.name)

            # Update instances
            try:
                queryset.update(**internal_values)
            except DatabaseError as exc:
                raise self._database_error_to_validation_error(exc) from exc

            # As `update()` invalidates the `_result_cache` of the queryset, we need to refetch the instances as the initial
            # query might have alter the instances to update (self-alterable queryset).
            # Postprocessing will decide to evaluate or not the queryset.
            queryset = self.get_queryset().filter(pk__in=pks)

            # Update many-to-many relationships: either create new relations or delete the obsolete ones. Existing are not touched.
            # We should have maximum 3 SQL queries per many-to-many field.
            for many_to_many_field, value in many_to_many.items():
                field = queryset.model._meta.get_field(many_to_many_field)
                through_model = field.remote_field.through

                through_src_field = field.path_infos[0].join_field.remote_field
                through_dst_field = field.path_infos[1].join_field.remote_field.field

                existing_vals = through_model.objects.filter(**{
                    f"{through_src_field.get_attname()}__in": pks,
                }).values(through_src_field.get_attname(), through_dst_field.get_attname(), through_model._meta.pk.name)

                existing_objs_map = {(item[through_src_field.get_attname()], item[through_dst_field.get_attname()]): item[through_model._meta.pk.name] for item in existing_vals}

                relations_to_create = []
                pks_to_keep = set()
                for pk in pks:
                    for new_value in value:
                        if (pk, new_value.pk) not in existing_objs_map:
                            relations_to_create.append(through_model(**{
                                through_src_field.get_attname(): pk,
                                through_dst_field.get_attname(): new_value.pk,
                            }))
                        else:
                            pks_to_keep.add(existing_objs_map[(pk, new_value.pk)])

                try:
                    pks_to_remove = set(existing_objs_map.values()) - set(pks_to_keep)
                    if pks_to_remove:
                        through_model.objects.filter(pk__in=pks_to_remove).delete()
                    if relations_to_create:
                        through_model.objects.bulk_create(
                            relations_to_create, ignore_conflicts=False
                        )
                except DatabaseError as exc:
                    raise self._database_error_to_validation_error(exc) from exc

            # Postprocess
            self._update_postprocess(queryset, internal_values)

        # Use `len(pks)` instead of `count = queryset.update()` because we want to include records even if no concrete fields were altered.
        # e.i.: partial update of only a m2m relations, the instance itself if not altered.
        return len(pks), queryset

    def _update_preprocess(
        self, queryset: models.QuerySet, update_fields: t.List[str]
    ) -> models.QuerySet:
        # TODO use update_fields to optimize field to fetch, for validation
        return queryset

    def _update_postprocess(
        self, queryset: models.QuerySet, update_values: t.Dict
    ):
        pass


class DeleteMixin:
    """Provides `delete`."""

    async def delete(self, filters: BaseModel) -> int:
        scoped_queryset = await self.apply_access_rules(self.get_queryset(), "delete")
        return await sync_to_async(self._delete_atomic, thread_sensitive=True)(
            scoped_queryset, filters
        )

    def _delete_atomic(self, scoped_queryset: models.QuerySet, filters: BaseModel) -> int:
        with transaction.atomic():
            queryset = scoped_queryset

            # apply filters
            if filters:
                queryset = self._apply_filters(queryset, filters)

            queryset = self._delete_preprocess(queryset)

            _, deleted_dict = queryset.delete()

            self._delete_postprocess()
        return deleted_dict.get(queryset.model._meta.label, 0)

    def _delete_preprocess(self, queryset: models.QuerySet) -> models.QuerySet:
        return queryset

    def _delete_postprocess(self):
        pass
