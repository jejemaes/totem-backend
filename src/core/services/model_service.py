import typing as t

from asgiref.sync import async_to_sync
from django.core import exceptions
from django.db import models, transaction
from django.db.models import F, ManyToManyField
from django.db.utils import DatabaseError
from ninja import FilterSchema
from pydantic import BaseModel

from core.orm.queryset import queryset_fetch_fields, queryset_order_by_fields
from user.access_policy import apply_access_rules, Context as AccessContext

from .base import BaseService, ServiceMeta
from .exceptions import ServiceValidationError, ServiceValidationMultiError


class ModelServiceMeta(ServiceMeta):
    def __new__(cls, name, bases, namespace):

        # Allow `_name` to be set explicitly in the service definition
        model_class = namespace.get("model", None)
        if namespace.get("_name", None) is None and model_class is not None:
            if issubclass(model_class, models.Model):
                namespace["_name"] = model_class._meta.label  # app.model_name
            else:
                namespace["_name"] = "__unknown__"

        new_class = super().__new__(cls, name, bases, namespace)
        return new_class


class ModelService(BaseService, metaclass=ModelServiceMeta):
    model = None

    ValidationError = ServiceValidationError

    # Configuration
    ordering_fields_nulls_last = "__all__"  # list of orm field names that should be ordered with nulls last, or '__all__' to apply to all fields.

    def get_queryset(self):
        return self.model.objects.all()

    # -----------------------------------------------------------------
    # Create
    # -----------------------------------------------------------------

    def create(self, data: t.List[BaseModel]) -> t.List[models.Model]:
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
            many_to_many_data = []
            for internal_values in internal_data:
                many_to_many = {}
                for field in queryset.model._meta.get_fields():
                    if (
                        isinstance(field, ManyToManyField)
                        and field.name in internal_values
                    ):
                        many_to_many[field.name] = internal_values.pop(field.name)
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
            queryset = self.apply_access_rules(queryset, "create")
            if queryset.filter(pk__in=[obj.pk for obj in instances]).count() != len(instances):
                raise exceptions.PermissionDenied("You do not have permission to create some of the objects.")

            # Save many-to-many relationships after the instance is created, and set it in the prefetch cache
            for instance, many_to_many_values in zip(instances, many_to_many_data):
                if many_to_many_values:
                    prefetched_objects = getattr(instance, "_prefetched_objects_cache", {})
                    for field_name, value in many_to_many.items():
                        field = getattr(instance, field_name)
                        # optimization: `set` will cause a read but since we are in a creation,
                        # there is no exsting relations.
                        field.add(*value)
                        # Set in cache in order to avoid refetching the m2m relation when serializing.
                        # This can be done since we are in creation mode. m2m cache value is a django queryset.
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

    # -----------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------

    def read(
        self, filters: t.Union[BaseModel, FilterSchema, t.Dict] = None, ordering=None, fields: t.List[str]=None
    ) -> models.QuerySet:
        """ Read records from the database applying access rules, filters, pagination, ordering and fields selection.
            :param filters: either
                - a pydantic model with the filter fields defined, the model_dump of the pydantic model will be used as kwargs for filtering the queryset
                - a ninja FilterSchema instance, the `filter` method of the FilterSchema will be used to filter the queryset
                - a dict with the filter fields and values, the dict will be used as lookups for filtering the queryset
            :param paginator: paginator to apply to the queryset, should be a ninja paginator
            :param ordering: list of fields to order by, should be a subset of the model fields
            :param fields: list of fields to select (model field name or relational lookup `my_fk_field__field_on_relation`),
                should be a subset of the model fields.

            Note: as pagination alters the result format, it can not be handled here.
        """
        queryset = self.get_queryset()
        # apply access rules
        queryset = self.apply_access_rules(queryset, "read")
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

    # -----------------------------------------------------------------
    # Update
    # -----------------------------------------------------------------

    def update(
        self, filters: BaseModel, data: BaseModel
    ) -> t.Tuple[int, t.List[models.Model]]:
        """ Update multiple records with the same data. """
        # Implement the update logic here
        with transaction.atomic():
            queryset = self.get_queryset()

            # Access rules check
            queryset = self.apply_access_rules(queryset, "update")

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
            pks = []
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
                count = queryset.update(**internal_values)
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

                pks_to_remove = set(existing_objs_map.values()) - set(pks_to_keep)
                if pks_to_remove:
                    through_model.objects.filter(pk__in=pks_to_remove).delete()
                if relations_to_create:
                    through_model.objects.bulk_create(relations_to_create, ignore_conflicts=True)

            # Postprocess
            self._update_postrocess(queryset, internal_values)

        return count, queryset

    def _update_preprocess(
        self, queryset: models.QuerySet, update_fields: t.List[str]
    ) -> models.QuerySet:
        # TODO use update_fields to optimize field to fetch, for validation
        return queryset

    def _update_postrocess(
        self, queryset: models.QuerySet, update_values: t.Dict
    ):
        pass

    # -----------------------------------------------------------------
    # Delete
    # -----------------------------------------------------------------

    def delete(self, filters: BaseModel) -> int:
        with transaction.atomic():
            queryset = self.get_queryset()
            # apply access rules
            queryset = self.apply_access_rules(queryset, "delete")

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

    # -----------------------------------------------------------------
    # Batch Update
    # -----------------------------------------------------------------

    # def batch_update(self, pk_data_map: dict) -> int:
    #     # Preprocess data
    #         internal_data = [self._to_internal_values(data) for values in data]
    #         update_fields = set()
    #         for internal_values in internal_data:
    #             update_fields |= set(
    #                 internal_values.keys()
    #             )

    # -----------------------------------------------------------------
    # Utils
    # -----------------------------------------------------------------

    def apply_access_rules(self, queryset: models.QuerySet, operation: str):
        context = AccessContext(user=self.context.user)
        return async_to_sync(apply_access_rules)(queryset, operation, context)

    def to_internal_values(
        self, data: t.List[BaseModel], exclude_unset: bool = False
    ) -> t.List[t.Dict]:
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
        for item in data:
            if not exclude_unset:
                fields = set(item.model_fields_set)
            else:
                fields = set(item.model_fields)

            for fk_fname in set(foreign_key_fields) & fields:
                foreign_key.setdefault(fk_fname, set())
                if getattr(item, fk_fname, None) is not None:
                    foreign_key[fk_fname] |= set([getattr(item, fk_fname)])

            for m2m_fname in set(many_to_many_fields) & fields:
                many_to_many.setdefault(m2m_fname, set())
                many_to_many[m2m_fname] |= set(getattr(item, m2m_fname, []))

        # fetch relations to minimize the number of queries.
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
        for index, item in enumerate(data):
            if not exclude_unset:
                fields = item.model_fields_set
            else:
                fields = set(item.model_fields)

            values = {}
            for fname in fields:
                suberror = ServiceValidationError({})

                if fname in many_to_many_instances:
                    invalid_values = []
                    valid_values = []
                    for v in getattr(item, fname, []):
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
                    if getattr(item, fname, None) not in foreign_key_instances[fname]:
                        suberror.add_message(
                            f"Invalid value for field '{fname}': {getattr(item, fname, None)}",
                            key=fname,
                        )
                    else:
                        values[fname] = foreign_key_instances[fname].get(
                            getattr(item, fname, None)
                        )

                else:
                    values[fname] = getattr(item, fname, None)

                if suberror:
                    error.add_error(index, suberror)

            result.append(values)

        # raise all error at once
        if error:
            raise error

        return result

    def validate_data(self, data: t.Dict, instance: models.Model) -> t.Dict:
        """ Validate the data for creation or update with the current instance (None for creation). This method 
            raises ValidationError in case of validation error and return nothing.
        """
        pass

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
