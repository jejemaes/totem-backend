"""Startup consistency checks for the API layer.

The controller-side mirror of `ServiceRegistry.validate()`: everything here would
otherwise fail -- or worse, pass silently -- on some later request. Runs at the
end of `CoreConfig.ready()`, once every `api` module is imported.

Scope: the schemas declared through the CRUD mixin attributes
(`*_request_schema` / `*_response_schema`). Schemas used by hand-written
`@route` methods are not inspected.
"""

from django.core.exceptions import ImproperlyConfigured
from pydantic import AliasChoices

from core.schemas.utils import _unwrap_list_schema
from core.services.registry import ServiceRegistry

from .controller import BaseModelController

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

    if errors:
        raise ImproperlyConfigured("\n".join(errors))


def _iter_controllers(base=BaseModelController, seen=None):
    seen = seen if seen is not None else set()
    for subclass in base.__subclasses__():
        if subclass not in seen:
            seen.add(subclass)
            yield subclass
        yield from _iter_controllers(subclass, seen)


def _check_request_schemas(controller):
    service_class = ServiceRegistry.get_service_class(controller.model)
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
