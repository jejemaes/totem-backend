import itertools
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple, Type, Union, cast

from django.db.models import Field as DjangoField
from django.db.models import ManyToManyRel, ManyToOneRel, Model
from ninja.errors import ConfigError
from ninja.schema import Schema
from pydantic import AliasChoices
from pydantic import create_model as create_pydantic_model

from .fields import convert_db_field
from .types import ExtraFieldInfos, SchemaKey

__all__ = ["SchemaFactory", "factory", "create_schema"]


class SchemaFactory:

    def __init__(self) -> None:
        self.schemas: Dict[SchemaKey, Type[Schema]] = {}
        self.schema_names: Set[str] = set()

    def create_schema(
        self,
        model: Type[Model],
        *,
        name: str = "",
        fields: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        optional_fields: Optional[List[str]] = None,
        custom_fields: Optional[List[Tuple[str, Any, Any]]] = None,
        base_class: Type[Schema] = Schema,
        extra_fields_kwargs: Dict[str, Dict[str, Any]] = None,
    ) -> Type[Schema]:
        name = name or model.__name__
        extra_fields_kwargs = extra_fields_kwargs or {}

        if fields and exclude:
            raise ConfigError("Only one of 'fields' or 'exclude' should be set.")

        key = self.get_key(
            model, name, fields, exclude, optional_fields, custom_fields, extra_fields_kwargs
        )
        if key in self.schemas:
            return self.schemas[key]

        model_fields_list = list(self._selected_model_fields(model, fields, exclude))
        if optional_fields:
            if optional_fields == "__all__":
                optional_fields = [f.name for f in model_fields_list]

        definitions = {}
        for fld in model_fields_list:
            extra_field_infos = extra_fields_kwargs.get(fld.name, {})
            extra_kwargs = ExtraFieldInfos(**extra_field_infos).model_dump(
                exclude_unset=True
            )
            python_type, field_info = convert_db_field(
                fld,
                optional=optional_fields and (fld.name in optional_fields),
                extra_kwargs=self._expand_alias(fld, extra_kwargs),
            )
            definitions[fld.name] = (python_type, field_info)

        if custom_fields:
            for fld_name, python_type, field_info in custom_fields:
                # if not isinstance(field_info, FieldInfo):
                #     field_info = Field(field_info)
                definitions[fld_name] = (python_type, field_info)

        if name in self.schema_names:
            name = self._get_unique_name(name)

        schema: Type[Schema] = create_pydantic_model(
            name,
            __config__=None,
            __base__=base_class,
            __module__=base_class.__module__,
            __validators__={},
            **definitions,
        )  # type: ignore
        # __model_name: str,
        # *,
        # __config__: ConfigDict | None = None,
        # __base__: None = None,
        # __module__: str = __name__,
        # __validators__: dict[str, AnyClassMethod] | None = None,
        # __cls_kwargs__: dict[str, Any] | None = None,
        # **field_definitions: Any,
        self.schemas[key] = schema
        self.schema_names.add(name)
        return schema

    @staticmethod
    def _expand_alias(fld: DjangoField, extra_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Expand a public rename (`alias`) into the pydantic aliases a response
        schema needs.

        The serialization side takes the alias, so the field goes out under its
        public name. The validation side must NOT be the alias alone: response
        schemas are built from ORM instances and from ORM-keyed dicts (list route),
        so the Django field name -- and the FK `attname`, since those dicts carry
        `<fk>_id` -- stay accepted as fallbacks.

        A request-body schema wanting a strict rename declares `validation_alias`
        directly instead (see `ExtraFieldInfos`); it passes through untouched.
        """
        alias = extra_kwargs.pop("alias", None)
        if not alias:
            return extra_kwargs
        if "validation_alias" in extra_kwargs:
            raise ConfigError(
                f"Field {fld.name!r}: 'alias' and 'validation_alias' are exclusive. "
                "Use 'alias' on a response schema, 'validation_alias' on a request one."
            )
        choices = [alias, fld.name]
        attname = getattr(fld, "attname", fld.name)
        if attname != fld.name:
            choices.append(attname)
        extra_kwargs["serialization_alias"] = alias
        extra_kwargs["validation_alias"] = AliasChoices(*choices)
        return extra_kwargs

    def get_key(
        self,
        model: Type[Model],
        name: str,
        fields: Union[str, List[str], None],
        exclude: Optional[List[str]],
        optional_fields: Optional[Union[List[str], str]],
        custom_fields: Optional[List[Tuple[str, str, Any]]],
        extra_fields_kwargs: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> SchemaKey:
        "returns a hashable value for all given parameters"
        # TODO: must be a test that compares all kwargs from init to get_key
        return (
            model,
            name,
            str(fields),
            str(exclude),
            str(optional_fields),
            str(custom_fields),
            str(extra_fields_kwargs),
        )

    def _get_unique_name(self, name: str) -> str:
        "Returns a unique name by adding counter suffix"
        for num in itertools.count(start=2):  # pragma: no branch
            result = f"{name}{num}"
            if result not in self.schema_names:
                break
        return result

    def _selected_model_fields(
        self,
        model: Type[Model],
        fields: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> Iterator[DjangoField]:
        "Returns iterator for model fields based on `exclude` or `fields` arguments"
        all_fields = {f.name: f for f in self._model_fields(model)}

        if not fields and not exclude:
            for f in all_fields.values():
                yield f

        invalid_fields = (set(fields or []) | set(exclude or [])) - all_fields.keys()
        if invalid_fields:
            raise ConfigError(
                f"DjangoField(s) {invalid_fields} are not in model {model}"
            )

        if fields:
            for name in fields:
                yield all_fields[name]
        if exclude:
            for f in all_fields.values():
                if f.name not in exclude:
                    yield f

    def _model_fields(self, model: Type[Model]) -> Iterator[DjangoField]:
        "returns iterator with all the fields that can be part of schema"
        for fld in model._meta.get_fields():  # pylint: disable=protected-access
            if isinstance(fld, (ManyToOneRel, ManyToManyRel)):
                # skipping relations
                continue
            yield cast(DjangoField, fld)


factory = SchemaFactory()

create_schema = factory.create_schema
