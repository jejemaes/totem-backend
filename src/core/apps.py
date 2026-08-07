from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # # Django Ninja consider model optional field as pydantic none required field, accepting
        # # NULL. We want only the field to be not required. Nullable should comes from the model.
        # try:
        #     from ._monkeypatch import monkeypatch_ninja
        #     monkeypatch_ninja()
        # except ImportError:
        #     pass

        # Since we register controller of django ninja extra in all `api` python module of each
        # django application, they need to loaded. In native django ninja, the route is
        # populated by importing every `api.py` file. This is not the case with controllers.
        autodiscover_modules('api')

        # Also, need to load all services defined
        autodiscover_modules("services")

        # Every service is loaded by now, so cross-service consistency can be
        # checked: a writable relation whose model has no service would only fail
        # on the first request carrying it.
        from .services.registry import ServiceRegistry

        ServiceRegistry.validate()
