from django.core.exceptions import ImproperlyConfigured


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
