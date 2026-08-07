from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured


class ServiceRegistry:
    """Maps a django model class to the service that serves it.

    Keyed by the model class rather than by a `"app.Model"` label: the generic
    relation-resolution code only ever holds model classes discovered by
    introspection, and a class key is navigable by the IDE and impossible to typo.
    """

    _by_model = {}

    @classmethod
    def register(cls, service_class):
        model = getattr(service_class, "model", None)
        if model is None:
            return

        registered = cls._by_model.get(model)
        if registered is not None and registered is not service_class:
            # Silent shadowing would make `env[Model]` return a different service
            # depending on import order. Fail at import time instead.
            raise ImproperlyConfigured(
                f"{service_class.__name__} and {registered.__name__} both serve "
                f"{model._meta.label}; a model must have a single service."
            )
        cls._by_model[model] = service_class

    @classmethod
    def get_service_class(cls, model):
        return cls._by_model.get(model)

    @classmethod
    def contains(cls, model):
        return model in cls._by_model

    @classmethod
    def keys(cls):
        return cls._by_model.keys()

    @classmethod
    def validate(cls):
        """Check that every writable relation can be resolved through a service.

        Resolution goes through `env[related_model]`, which raises when the related
        model has no service. Without this check that failure would surface as a
        runtime error on the first request carrying the relation; here it surfaces at
        startup instead.

        Scoped to the fields declared by the input schemas, deliberately not to
        `model._meta.get_fields()`: a model inherits relations it never exposes for
        writing -- `AbstractUser` brings `groups` and `user_permissions`, which will
        never have a service -- and requiring one for those would be meaningless.

        Must run after every `services` module is imported, so it belongs at the end
        of `CoreConfig.ready()` rather than in `__init_subclass__`, where the service
        of a related model may not be loaded yet.
        """
        errors = []
        for model, service_class in cls._by_model.items():
            schemas = (
                getattr(service_class, "create_schema", None),
                getattr(service_class, "update_schema", None),
            )
            for schema in schemas:
                if schema is None:
                    continue
                for field_name in schema.model_fields:
                    try:
                        field = model._meta.get_field(field_name)
                    except FieldDoesNotExist:
                        errors.append(
                            f"{service_class.__name__}: {schema.__name__} declares "
                            f"{field_name!r}, absent from {model._meta.label}."
                        )
                        continue

                    if not field.is_relation or field.related_model is None:
                        continue
                    if field.related_model not in cls._by_model:
                        errors.append(
                            f"{service_class.__name__}: {schema.__name__} accepts the "
                            f"relation {field_name!r} but "
                            f"{field.related_model._meta.label} has no service, so it "
                            f"cannot be resolved with access rules."
                        )

        if errors:
            raise ImproperlyConfigured("\n".join(errors))
