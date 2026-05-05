
import typing as t
from collections.abc import Mapping
from weakref import WeakSet

from django.conf import settings
from django.db.models import Model
from django.contrib.auth import get_user_model

from .registry import ServiceRegistry
from .base import Service

User = get_user_model()


class Environment(Mapping[str, Model]):

    user: User | None
    language: str | None
    tz: str | None
    context: dict | None

    registry: ServiceRegistry = ServiceRegistry

    def __new__(cls, user=None, language=None, tz=None, context: dict | None = None):
        if context is None:
            context = {}
        if language is None:
            language = settings.LANGUAGE_CODE
        if tz is None:
            tz = settings.TIME_ZONE

        # if env already exists, return it
        for env in _envs:
            if env.user == user and env.language == language and env.tz == tz and env.context == context:
                return env

        # otherwise create environment, and add it in the set
        self = object.__new__(cls)
        self.user = user
        self.language = language
        self.tz = tz
        self.context = context

        _envs.add(self)

        return self

    def __setattr__(self, name: str, value: t.Any) -> None:
        # once initialized, attributes are read-only
        if name in vars(self):
            raise AttributeError(f"Attribute {name!r} is read-only, call `env()` instead")
        return super().__setattr__(name, value)

    #
    # Mapping methods
    #

    def __contains__(self, service_name) -> bool:
        """ Test whether the given service exists. """
        return self.registry.contains(service_name)

    def __getitem__(self, service_name: str) -> Service:
        """ Return an empty service instance from the given service name. """
        service_class = self.registry.get_service_class(service_name)
        if service_class is None:
            raise KeyError(f"Service {service_name!r} not found")
        return service_class(self, (), ())

    def __iter__(self):
        """ Return an iterator on service names. """
        return iter(self.registry)

    def __len__(self):
        """ Return the size of the service registry. """
        return len(self.registry)

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __hash__(self):
        return object.__hash__(self)

    def __call__(
        self,
        user: User | None = None,
        language: str | None = None,
        tz: str | None = None,
        context: dict | None = None,
    ) -> "Environment":
        """ Return a new environment with the given context values updated. """
        if context is None:
            context = {}
        if language is None:
            language = settings.LANGUAGE_CODE
        if tz is None:
            tz = settings.TIME_ZONE
        return Environment(user, language, tz, context)


_envs = WeakSet[Environment]()
