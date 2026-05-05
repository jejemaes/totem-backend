import typing as t

from pydantic import BaseModel
from django.db import models
from django.db.models.constants import LOOKUP_SEP

from core.schemas.metaclass import ModelSchema

from functools import lru_cache


def schema_to_orm_fields(schema: ModelSchema, model_class: models.Model) -> t.List[str]:
    if hasattr(schema, "__origin__") and (
        schema.__origin__ is list or schema.__origin__ is t.List
    ):
        schema = schema.__args__[0]

    return {
        fname: fspec["source"]
        for fname, fspec in extract_orm_fields_map(schema, model_class).items()
    }


@lru_cache()
def extract_orm_fields_map(schema: ModelSchema, model_class: models.Model) -> t.Dict[str, t.Union[str, t.Dict[str, str]]]:
    """
    Extracts the ORM fields from a ModelSchema instance.

    Args:
        schema (ModelSchema): The ModelSchema instance to extract fields from.
        model_class (models.Model): The Django model class associated with the schema.

    Returns:
        Dict[str, Dict]: A dictionary pydantic schema field name to their corresponding ORM model
        field names or nested dictionaries for related fields.
        Example:
        ```
        {
            "roles": {
                "source": "roles",
                "fields": {
                    "id": {
                        "source": "id"
                    },
                    "name": {
                        "source": "name"
                    }
                }
            },
            "id": {
                "source": "id"
            },
            "username": {
                "source": "username"
            },
            ...
        }
        ```
    """
    if model_class is None:
        model_class = schema.Meta.model
    model_fields_map = {f.name: f for f in model_class._meta.get_fields()}

    orm_fields = {}
    for field_name, field_info in schema.model_fields.items():
        orm_fname = field_info.serialization_alias or field_name
        if orm_fname not in model_fields_map:
            continue
        model_field = model_fields_map[orm_fname]

        if model_field.is_relation:
            orm_fields[field_name] = {"source": orm_fname, "fields": {}}
            # Add related fields for foreign keys, ManyToMany, and OneToOne relationships
            if hasattr(model_field, "related_model") and model_field.related_model:
                related_model = model_field.related_model
                for subschema in extract_schemas_from_annotation(field_info.annotation):
                    orm_fields[orm_fname]["fields"].update(
                        extract_orm_fields_map(subschema, related_model)
                    )
        else:
            orm_fields[field_name] = {"source": orm_fname}
    return orm_fields


# def extract_orm_fields(schema: ModelSchema, model_class: models.Model) -> t.List[str]:
#     """
#     Extracts the ORM fields from a ModelSchema instance.

#     Args:
#         schema (ModelSchema): The ModelSchema instance to extract fields from.
#         model_class (models.Model): The Django model class associated with the schema.

#     Returns:
#         List[str]: A list of ORM field names (or lookup paths for related fields).
#     """
#     if model_class is None:
#         model_class = schema.Meta.model
#     model_fields_map = {f.name: f for f in model_class._meta.get_fields()}

#     orm_fields = []
#     for field_name, field_info in schema.model_fields.items():
#         orm_fname = field_info.serialization_alias or field_name
#         if orm_fname not in model_fields_map:
#             continue
#         model_field = model_fields_map[field_name]

#         if model_field.is_relation:
#             orm_fields.append(orm_fname)
#             # Add related fields for foreign keys, ManyToMany, and OneToOne relationships
#             if hasattr(model_field, "related_model") and model_field.related_model:
#                 related_model = model_field.related_model
#                 for subschema in extract_schemas_from_annotation(field_info.annotation):
#                     orm_fields.extend(
#                         [f"{orm_fname}{LOOKUP_SEP}{fname}" for fname in extract_orm_fields(subschema, related_model)]
#                     )
#         else:
#             orm_fields.append(orm_fname)
#     return orm_fields


def extract_schemas_from_annotation(annotation):
    if annotation is type(None):
        return []
    if hasattr(annotation, "__origin__") and annotation.__origin__ in (t.Union,):
        schemas = []
        for arg in annotation.__args__:
            schemas.extend(extract_schemas_from_annotation(arg))
        return schemas
    if hasattr(annotation, "__origin__") and annotation.__origin__ in (list, t.List):
        return extract_schemas_from_annotation(annotation.__args__[0])
    elif isinstance(annotation, type) and issubclass(annotation, ModelSchema):
        return [annotation]
    return []


def extract_orm_fields_from_specs(orm_field_map: t.Dict[str, t.Any], field_names: t.List[str]) -> t.List[str]:
    """
    Extracts the ORM fields based on the provided field names and the ORM field map.

    Args:
        orm_field_map (Dict[str, Any]): A mapping of schema field names to their corresponding ORM field names or nested dictionaries.
        field_names (List[str]): A list of schema field names to extract ORM fields for.

    Returns:
        List[str]: A list of ORM field names corresponding to the provided schema field names.
    """
    orm_fields = []
    for name in field_names:
        if name not in orm_field_map:
            continue

        orm_fields.append(orm_field_map[name]["source"])
        if "fields" in orm_field_map[name]: # relational fields
            nested_fields = extract_orm_fields_from_specs(orm_field_map[name]["fields"], list(orm_field_map[name]["fields"].keys()))
            orm_fields.extend([f"{orm_field_map[name]['source']}{LOOKUP_SEP}{nf}" for nf in nested_fields])
    return orm_fields


def model_instance_to_dict(
    model_instance: BaseModel, exclude_unset: bool = True
) -> dict:
    """Converts a Pydantic model instance to a dictionary, optionally excluding unset fields."""
    if exclude_unset:
        field_list = list(model_instance.model_fields_set)
    else:
        field_list = list(model_instance.model_fields)

    values = {}
    for field in field_list:
        values[field] = getattr(model_instance, field, None)
    return values
