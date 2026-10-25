"""Startup consistency checks for the API layer.

The controller-side mirror of `ServiceRegistry.validate()`: everything here would
otherwise fail -- or worse, pass silently -- on some later request. Runs at the
end of `CoreConfig.ready()`, once every `api` module is imported.

Scope: the schemas declared through the CRUD mixin attributes
(`*_request_schema` / `*_response_schema`). Schemas used by hand-written
`@route` methods are not inspected.
"""

from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from ninja.signature.utils import get_path_param_names
from ninja.utils import normalize_path
from pydantic import AliasChoices

from core.orm.fields.computed.utils import VIRTUAL, computed_fields, get_computed_field

from core.schemas.utils import _unwrap_list_schema

from .controller import (
    BaseModelController,
    DisplayNameModelControllerMixin,
    GroupByModelControllerMixin,
    ResequenceModelControllerMixin,
)

REQUEST_TO_SERVICE_SCHEMA = (
    ("create_request_schema", "create_schema"),
    ("update_request_schema", "update_schema"),
)
RESPONSE_SCHEMA_ATTRIBUTES = (
    "list_response_schema",
    "retrieve_response_schema",
    "create_response_schema",
    "update_response_schema",
)


def validate_controllers():
    """Check that every model controller is consistent with its service and that
    field renames sit on the right side of the wire.

    * Every field of a request schema must be accepted by the service's input
      schema: `_input_values` extracts values along the service schema, so a field
      the service does not declare is silently dropped from the payload.
    * A request schema must not carry a response-style rename (`alias`): its
      validation side accepts the Django field name as a fallback, which would let
      undocumented names into the body contract.
    * A response schema must keep every renamed field readable under its Django
      field name: it is built from ORM instances (retrieve/create/update) and
      ORM-keyed dicts (list), and pydantic only looks attributes up through the
      validation aliases. A field that loses that fallback silently disappears
      from responses.
    """
    errors = []
    for controller in sorted(_iter_controllers(), key=lambda cls: cls.__name__):
        if getattr(controller, "model", None) is None:
            continue
        errors.extend(_check_request_schemas(controller))
        errors.extend(_check_response_schemas(controller))
        errors.extend(_check_derived_fields(controller))
        errors.extend(_check_path_parameters(controller))
        errors.extend(_check_resequence_route(controller))
        errors.extend(_check_display_name_route(controller))
        errors.extend(_check_group_by_route(controller))

    if errors:
        raise ImproperlyConfigured("\n".join(errors))


def _iter_controllers(base=BaseModelController, seen=None):
    seen = seen if seen is not None else set()
    for subclass in base.__subclasses__():
        if subclass not in seen:
            seen.add(subclass)
            yield subclass
        yield from _iter_controllers(subclass, seen)


def _check_resequence_route(controller):
    return _check_static_route(controller, ResequenceModelControllerMixin, "resequence", "/resequence/")


def _check_display_name_route(controller):
    return _check_static_route(controller, DisplayNameModelControllerMixin, "display_name", "/display-name/")


def _check_group_by_route(controller):
    return _check_static_route(controller, GroupByModelControllerMixin, "group_by", "/group-by/")


def _check_static_route(controller, mixin, name, route):
    """A controller inheriting `mixin` registers its fixed-path `route`, and before
    `/{id}/`.

    Neither is visible otherwise: misplaced in the bases, the mixin registers
    nothing, or registers after `/{id}/`, which takes the fixed segment for an id;
    the client gets a 405 or a 404, never the route. Read from the class `__dict__`,
    whose order is the order the routes are registered in.
    """
    if not issubclass(controller, mixin) or controller.model is None:
        return
    names = list(controller.__dict__)
    if name not in names:
        yield (
            f"{controller.__name__}: inherits {mixin.__name__} but registers "
            f"no {route} route. Put the mixin before ModelController in the bases."
        )
        return
    shadowing = [
        other for other in ("retrieve", "update", "delete")
        if other in names and names.index(other) < names.index(name)
    ]
    if shadowing:
        yield (
            f"{controller.__name__}: {route} is registered after the /{{id}}/ routes "
            f"({', '.join(shadowing)}), which take it for an id. Put "
            f"{mixin.__name__} before the CRUD mixins in the bases."
        )


def _check_path_parameters(controller):
    """The parameters of a nested prefix (`/budgets/{budget_id}/lines/`) name the
    record the resources belong to, and nothing else may.

    * Each must be a field of the model: the routes filter on it as an ORM lookup,
      and a creation sets the field it resolves to (`budget_id` sets `budget`).
    * The list filters must not declare it under either name: ANDed with the path,
      such a filter could only empty the list, while the client would believe it
      chooses the record.
    * The create body must not carry the field: the path sets it, and a body value
      would be silently overridden.
    """
    params = get_path_param_names(normalize_path(controller.path_prefix))
    if not params:
        return
    model = controller.model
    filter_schema = getattr(controller, "list_filter_schema", None)
    create_schema = getattr(controller, "create_request_schema", None)
    for param in params:
        try:
            field_name = model._meta.get_field(param).name
        except FieldDoesNotExist:
            yield (
                f"{controller.__name__}: the path parameter {param!r} of "
                f"{controller.path_prefix!r} is no field of {model.__name__}."
            )
            continue
        names = {param, field_name}
        if filter_schema is not None and names & set(filter_schema.model_fields):
            yield (
                f"{controller.__name__}: {filter_schema.__name__} declares "
                f"{sorted(names & set(filter_schema.model_fields))}, which the path "
                f"parameter {param!r} already decides."
            )
        if create_schema is not None and names & set(create_schema.model_fields):
            yield (
                f"{controller.__name__}: {create_schema.__name__} declares "
                f"{sorted(names & set(create_schema.model_fields))}, which the path "
                f"parameter {param!r} sets."
            )


def _check_request_schemas(controller):
    service_class = controller.service
    for request_attr, service_attr in REQUEST_TO_SERVICE_SCHEMA:
        request_schema = getattr(controller, request_attr, None)
        if request_schema is None:
            continue

        for field_name, field_info in request_schema.model_fields.items():
            if (
                field_info.serialization_alias
                and field_info.serialization_alias != field_name
            ):
                yield (
                    f"{controller.__name__}: {request_schema.__name__}.{field_name} "
                    f"carries a response-style rename (alias "
                    f"{field_info.serialization_alias!r}). A request schema renames "
                    f"with 'validation_alias', so the body accepts only the public name."
                )
            elif _is_lax_rename(field_name, field_info.validation_alias):
                yield (
                    f"{controller.__name__}: {request_schema.__name__}.{field_name} "
                    f"accepts both its public name and the Django field name in the "
                    f"body. A request schema renames with 'validation_alias' alone."
                )

        service_schema = getattr(service_class, service_attr, None) if service_class else None
        if service_schema is None:
            continue
        dropped = set(request_schema.model_fields) - set(service_schema.model_fields)
        if dropped:
            yield (
                f"{controller.__name__}: {request_schema.__name__} declares "
                f"{sorted(dropped)}, which {service_schema.__name__} does not accept; "
                f"the service would silently drop them from every payload."
            )


def _check_response_schemas(controller):
    for response_attr in RESPONSE_SCHEMA_ATTRIBUTES:
        response_schema = getattr(controller, response_attr, None)
        if response_schema is None:
            continue
        response_schema = _unwrap_list_schema(response_schema)

        for field_name, field_info in response_schema.model_fields.items():
            if not _is_readable_by_field_name(field_name, field_info.validation_alias):
                yield (
                    f"{controller.__name__}: {response_schema.__name__}.{field_name} "
                    f"cannot be read back under its Django field name "
                    f"(validation_alias {field_info.validation_alias!r}), so it would "
                    f"silently disappear from responses. A response schema renames "
                    f"with 'alias', which keeps the ORM name as a fallback."
                )


def _is_derived(model, field_name) -> bool:
    "A computed field, stored or virtual, or a generated column."
    if get_computed_field(model, field_name) is not None:
        return True
    try:
        return isinstance(model._meta.get_field(field_name), models.GeneratedField)
    except FieldDoesNotExist:
        return False


def _check_derived_fields(controller):
    """Derived fields are read-only, and only loadable where the service loads them.

    * A request schema -- the controller's or its service's -- must not list a
      computed field or a generated column: the value is derived, never written by
      a client. Nothing else would stop it: the converter handles them like any
      field, and a stored computed field is a real column `queryset.update()`
      would happily overwrite (a generated one would fail in the database).
    * A response schema must not read a *virtual* computed field through a
      relation: `apply_query_fields` loads the virtual fields of the controller's
      own model, while nested prefetches are built by `queryset_fetch_fields`,
      which knows nothing about them. The value would be fetched per instance, from
      a coroutine.
    * Ordering by a virtual computed field is not supported: it is no column.
    """
    model = controller.model
    service_class = controller.service

    checked = set()
    for request_attr, service_attr in REQUEST_TO_SERVICE_SCHEMA:
        for schema in (
            getattr(controller, request_attr, None),
            getattr(service_class, service_attr, None) if service_class else None,
        ):
            if schema is None or schema in checked:
                continue
            checked.add(schema)
            for field_name in schema.model_fields:
                if _is_derived(model, field_name):
                    yield (
                        f"{controller.__name__}: {schema.__name__}.{field_name} is a "
                        f"derived field, which is read-only: it cannot be part of an "
                        f"input schema."
                    )

    for response_attr in RESPONSE_SCHEMA_ATTRIBUTES:
        response_schema = getattr(controller, response_attr, None)
        if response_schema is None:
            continue
        for lookup in controller._response_orm_fields(response_schema):
            *relations, name = lookup.split(LOOKUP_SEP)
            if not relations:
                continue
            related_model = model
            for relation in relations:
                related_model = related_model._meta.get_field(relation).related_model
            if name in computed_fields(related_model, VIRTUAL):
                yield (
                    f"{controller.__name__}: {response_attr} reads the virtual "
                    f"computed field {related_model.__name__}.{name} through "
                    f"'{LOOKUP_SEP.join(relations)}'. Only the virtual fields of "
                    f"{model.__name__} itself are loaded: make it stored, or drop it "
                    f"from the nested schema."
                )

    for ordering in getattr(controller, "list_ordering_fields", None) or []:
        name = ordering.lstrip("-")
        if name in computed_fields(model, VIRTUAL):
            yield (
                f"{controller.__name__}: list_ordering_fields orders by the virtual "
                f"computed field {name!r}, which is no column. Only a stored one can "
                f"be ordered by."
            )


def _is_lax_rename(field_name, validation_alias):
    "True when a rename exists AND the Django field name is still accepted."
    if not isinstance(validation_alias, AliasChoices):
        return False
    choices = [c for c in validation_alias.choices if isinstance(c, str)]
    return field_name in choices and any(c != field_name for c in choices)


def _is_readable_by_field_name(field_name, validation_alias):
    if validation_alias is None or validation_alias == field_name:
        return True
    if isinstance(validation_alias, AliasChoices):
        return field_name in validation_alias.choices
    return False
