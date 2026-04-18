import datetime
import typing as t
from enum import Enum
from functools import singledispatch

from django.contrib.postgres import fields as psql_fields
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models.fields import Field
from pydantic import UUID4, AnyUrl, EmailStr, IPvAnyAddress
from pydantic.fields import FieldInfo as PydanticField
from pydantic_core import PydanticUndefined

from core.schemas.relations import create_foreignkey_field
from core.schemas.types import AnyObject
from core.schemas.validators import convert_validators

# -----------------------------------------
# Main method
# -----------------------------------------


def convert_db_field(
    field: Field,
    optional: bool = False,
    extra_kwargs: dict = None,
) -> t.Tuple[t.Type, PydanticField]:
    converted = convert_django_field(
        field,
        optional=optional,
        extra_kwargs=extra_kwargs,
    )
    return converted


# -----------------------------------------
# Helpers
# -----------------------------------------


def _get_enum_choices(
    choices: t.Iterable[t.Tuple[t.Any, str]],
) -> t.Iterator[t.Tuple[str, str, str]]:
    for value, help_text in choices:
        name = value.upper().replace("-", "_")
        description = help_text
        yield name, value, description


def _get_pydantic_fieldinfo_from_field(
    python_type: t.Type, field: Field, optional: bool, extra_kwargs: t.Dict = None
) -> t.Tuple[t.Type, PydanticField]:
    # django field options
    nullable = False

    field_options = field.deconstruct()[3]
    blank = field_options.get("blank", False)
    null = field_options.get("null", False)
    title = field.verbose_name.title() if field.verbose_name else field.name
    description = field.help_text.title().strip()

    # handle choices
    validators = field.validators
    if field.choices:
        named_choices = [(c[0], c[1]) for c in _get_enum_choices(field.choices)]
        python_type = Enum(  # type: ignore
            f"{field.name.title().replace('_', '')}Enum",
            named_choices,
            type=python_type,  # combine Enum with base python type (IntEnum, StrEnum, ...)
        )
        # `MaxLen` annotated type validator can not be applied on Enum Type.
        validators = [
            v for v in field.validators if not isinstance(v, MaxLengthValidator)
        ]
        # extends description with bullet point with choices and human readdable description
        description += "\n".join(
            f"* `{str(value)}` - {label}" for value, label in field.choices
        )

    field_infos = {
        "description": description or None,
        "title": title,
        "default": ...,
        "default_factory": None,
    }

    if field.primary_key or blank or null or optional:
        field_infos["default"] = None
        nullable = True

    if field.has_default():
        if callable(field.default):
            field_infos["default_factory"] = field.default
        else:
            field_infos["default"] = field.default

    if field_infos["default_factory"]:
        field_infos["default"] = PydanticUndefined

    # django field validators
    extra_field_infos, extra_validators = convert_validators(validators)
    if extra_field_infos:
        field_infos.update(extra_field_infos)
    if extra_validators:
        python_type = t.Annotated[python_type, *extra_validators]

    if nullable:
        python_type = t.Optional[python_type]

    # inject extra kwargs
    if extra_kwargs:
        field_infos.update(extra_kwargs)

    return (
        python_type,
        PydanticField(**field_infos),
    )


# -----------------------------------------
# Django Fields Converter
# -----------------------------------------


@singledispatch
def convert_django_field(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    raise ImproperlyConfigured(
        f"Don't know how to convert the Django field {field} ({field, field.__class__})"
    )


# Strings


@convert_django_field.register(models.CharField)
@convert_django_field.register(models.TextField)
def convert_django_charfield(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        str, field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(models.SlugField)
def convert_django_slugfield(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        str, field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(models.EmailField)
def convert_django_emailfield(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        EmailStr, field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(models.URLField)
def convert_django_urlfield(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        AnyUrl, field, optional=optional, extra_kwargs=extra_kwargs
    )


# Integer


@convert_django_field.register(models.AutoField)
@convert_django_field.register(models.PositiveIntegerField)
@convert_django_field.register(models.PositiveSmallIntegerField)
@convert_django_field.register(models.SmallIntegerField)
@convert_django_field.register(models.BigIntegerField)
@convert_django_field.register(models.IntegerField)
def convert_field_to_int(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        int, field, optional=optional, extra_kwargs=extra_kwargs
    )


# Float


@convert_django_field.register(models.FloatField)
@convert_django_field.register(models.DecimalField)
def convert_field_to_float(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        float, field, optional=optional, extra_kwargs=extra_kwargs
    )


# Boolean


@convert_django_field.register(models.BooleanField)
@convert_django_field.register(models.NullBooleanField)
def convert_field_to_boolean(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        bool, field, optional=optional, extra_kwargs=extra_kwargs
    )


# IP


@convert_django_field.register(models.IPAddressField)
@convert_django_field.register(models.GenericIPAddressField)
def convert_field_to_ip(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        IPvAnyAddress, field, optional=optional, extra_kwargs=extra_kwargs
    )


# URL


@convert_django_field.register(models.URLField)
def convert_field_to_url(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        AnyUrl, field, optional=optional, extra_kwargs=extra_kwargs
    )


# Binary ??


# File


@convert_django_field.register(models.FileField)
@convert_django_field.register(models.FilePathField)
def convert_field_to_date(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        str, field, optional=optional, extra_kwargs=extra_kwargs
    )


# Date, Datime, Time


@convert_django_field.register(models.DateField)
def convert_field_to_date(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        datetime.date, field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(models.DateTimeField)
def convert_field_to_datetime(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        datetime.datetime, field, optional=optional
    )


@convert_django_field.register(models.TimeField)
def convert_field_to_time(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        datetime.time, field, optional=optional, extra_kwargs=extra_kwargs
    )


# Duration


@convert_django_field.register(models.DurationField)
def convert_field_to_timedelta(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        datetime.timedelta, field, optional=optional
    )


# UUID


@convert_django_field.register(models.UUIDField)
def convert_field_to_uuid(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        UUID4, field, optional=optional, extra_kwargs=extra_kwargs
    )


# One-to-Many relation


@convert_django_field.register(models.OneToOneField)
@convert_django_field.register(models.ForeignKey)
def convert_field_to_many_to_one(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    pk_field = field.related_model._meta.pk  # pylint: disable=protected-access
    python_type, field_info = convert_db_field(
        pk_field, optional=optional, extra_kwargs=extra_kwargs
    )
    return python_type, field_info


# Many-to-Many relation


@convert_django_field.register(models.ManyToManyField)
@convert_django_field.register(models.ManyToManyRel)
@convert_django_field.register(models.ManyToOneRel)
def convert_field_to_many_to_many(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    python_type, field_info = _get_pydantic_fieldinfo_from_field(
        str,  # don't care about the type here, just want field infos
        field,
        optional=optional,
    )
    return t.List[python_type], field_info


# -----------------------------------------
# Postgres Contrib Fields Converter
# -----------------------------------------


@convert_django_field.register(psql_fields.JSONField)
def convert_field_to_json(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        AnyObject, field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(psql_fields.ArrayField)
def convert_field_to_arrayfield(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    python_type, dummy = convert_db_field(field=field.base_field)
    return _get_pydantic_fieldinfo_from_field(
        t.List[python_type], field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(psql_fields.CICharField)
@convert_django_field.register(psql_fields.CIEmailField)
@convert_django_field.register(psql_fields.CITextField)
def convert_field_to_ci_fields(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        str, field, optional=optional, extra_kwargs=extra_kwargs
    )


@convert_django_field.register(psql_fields.HStoreField)
def convert_field_to_hstorefield(
    field: Field, optional: bool = False, extra_kwargs: dict = None
) -> t.Tuple[t.Type, PydanticField]:
    return _get_pydantic_fieldinfo_from_field(
        t.Dict, field, optional=optional, extra_kwargs=extra_kwargs
    )
