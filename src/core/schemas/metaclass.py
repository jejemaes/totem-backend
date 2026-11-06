import annotationlib
import typing as t

from django.db.models import Model as DjangoModel
from ninja.errors import ConfigError
from ninja.schema import ResolverMetaclass, Schema
from pydantic.dataclasses import dataclass

from .factory import create_schema

_is_modelschema_class_defined = False


@dataclass
class MetaConf:
    model: t.Any
    fields: t.Optional[t.List[str]] = None
    exclude: t.Union[t.List[str], str, None] = None
    fields_optional: t.Union[t.List[str], str, None] = None
    extra_fields_kwargs: t.Optional[t.Dict[str, t.Dict[str, t.Any]]] = None

    @staticmethod
    def from_schema_class(name: str, namespace: dict) -> "MetaConf":
        if "Config" in namespace:
            raise ConfigError(  # pragma: no cover
                "The use of `Config` class is removed for ModelSchema, use 'Meta' instead",
            )
        if "Meta" in namespace:
            meta = namespace["Meta"]
            model = meta.model
            fields = getattr(meta, "fields", None)
            exclude = getattr(meta, "exclude", None)
            optional_fields = getattr(meta, "optional_fields", None)
            extra_fields_kwargs = getattr(meta, "extra_fields_kwargs", {})

        else:
            raise ConfigError(f"ModelSchema class '{name}' requires a 'Meta' subclass")

        assert issubclass(model, DjangoModel)

        if not fields and not exclude:
            raise ConfigError(
                "Creating a ModelSchema without either the 'fields' attribute"
                " or the 'exclude' attribute is prohibited"
            )

        if fields == "__all__":
            fields = None
            # ^ when None is passed to create_schema - all fields are selected

        return MetaConf(
            model=model,
            fields=fields,
            exclude=exclude,
            fields_optional=optional_fields,
            extra_fields_kwargs=extra_fields_kwargs,
        )


class ModelSchemaMetaclass(ResolverMetaclass):

    def __new__(
        mcs,
        name: str,
        bases: tuple,
        namespace: dict,
        **kwargs,
    ):
        cls = super().__new__(
            mcs,
            name,
            bases,
            namespace,
            **kwargs,
        )
        for base in reversed(bases):
            if (
                _is_modelschema_class_defined
                and issubclass(base, ModelSchema)
                and base == ModelSchema
            ):
                meta_conf = MetaConf.from_schema_class(name, namespace)

                custom_fields = []
                # PEP 649: the namespace holds a lazy `__annotate__` function
                # instead of an `__annotations__` dict.
                annotate = annotationlib.get_annotate_from_class_namespace(namespace)
                annotations = (
                    annotationlib.call_annotate_function(
                        annotate, annotationlib.Format.FORWARDREF
                    )
                    if annotate
                    else {}
                )
                for attr_name, _type in annotations.items():
                    if attr_name.startswith("_"):
                        continue
                    default = namespace.get(attr_name, ...)
                    custom_fields.append((attr_name, _type, default))

                model_schema = create_schema(
                    meta_conf.model,
                    name=name,
                    fields=meta_conf.fields,
                    exclude=meta_conf.exclude,
                    optional_fields=meta_conf.fields_optional,
                    custom_fields=custom_fields,
                    base_class=cls,
                    extra_fields_kwargs=meta_conf.extra_fields_kwargs,
                )
                model_schema.__doc__ = cls.__doc__
                return model_schema

        return cls


class ModelSchema(Schema, metaclass=ModelSchemaMetaclass):
    pass


_is_modelschema_class_defined = True
