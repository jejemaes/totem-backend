import typing as t

from dict_deep import deep_set
from django.db.models import Model, Prefetch, QuerySet
from django.db.models.constants import LOOKUP_SEP


def queryset_fetch_fields(queryset: QuerySet, field_lookups: t.List[str]) -> QuerySet:
    """ Modifies the given queryset to fetch only the specified fields, including related fields.
    :param queryset: The initial queryset to modify.
    :param field_lookups: A list of field lookups to fetch, which can include related fields using Django's lookup syntax (e.g., 'roles__id').
    :return: A modified queryset that fetches only the specified fields.
    """
    # Need to sort otherwise the non related field will override the related field in the lookup_map
    # Ex: 'roles' must be processed before 'roles__id' otherwise 'roles' will override 'roles__id'
    # # in the lookup_map and we will lose the information that we need to fetch 'id' field of the related model 'roles'
    field_lookups.sort(reverse=False)

    field_splits = [f.split(LOOKUP_SEP) for f in field_lookups]
    lookup_map = {}
    for item in field_splits:
        deep_set(lookup_map, item, {})

    only_fields, prefetches = model_prepare_fetch_fields(queryset.model, lookup_map)
    if only_fields:
        queryset = queryset.only(*only_fields)
    else:
        pk_fname = queryset.model._meta.pk.name  # pylint: disable=protected-access
        queryset = queryset.only(pk_fname)

    for dummy, prefetch_obj in prefetches.items():
        queryset = queryset.prefetch_related(prefetch_obj)
    return queryset


def model_prepare_fetch_fields(model: Model, field_lookups: t.Dict[str, t.Dict[str, t.Any]]) -> t.Tuple[t.Set[str], t.Dict[str, t.Dict]]:
    only_fields = set()
    prefetch = {}
    for fname, fval in field_lookups.items():
        field = model._meta.get_field(fname)
        if field.is_relation:
            related_model = field.related_model

            prefetch_current_field = False
            # TODO: optimize with maybe check JOIN and select_related if so
            if field.one_to_one or field.many_to_one:
                if fval: # need fields of the ForeignKey
                    prefetch_current_field = True
            elif field.many_to_many or field.one_to_many:
                prefetch_current_field = True

            if prefetch_current_field:
                related_only_fields, related_prefetch = model_prepare_fetch_fields(related_model, fval)
                qs = related_model.objects.all()
                if related_only_fields:
                    qs = qs.only(*related_only_fields)
                if related_prefetch:
                    for rlookup, rprefetch_info in related_prefetch.items():
                        qs = qs.prefetch_related(
                            Prefetch(
                                rlookup,
                                queryset=rprefetch_info["queryset"],
                                to_attr=fname
                            )
                        )
                prefetch[fname] = Prefetch(
                    fname,
                    queryset=qs,
                )
        else:
            only_fields.add(fname)
    return only_fields, prefetch


def model_instance_to_dict(instance) -> t.Dict[str, t.Any]:
    """ Converts a Django model instance to a dictionary with only the fetched fields, including prefetched related objects.
        For relations, the result dict will contain a list of related objects converted to dicts as well.
    """
    values = {}
    for key, value in instance.__dict__.items():
        if key not in ["_state", "_prefetched_objects_cache"]:
            values[key] = value
    for key, value in instance.__dict__.get("_prefetched_objects_cache", {}).items():
        values[key] = [model_instance_to_dict(i) for i in value]
    return values
