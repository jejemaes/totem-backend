import typing as t
from types import MappingProxyType

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model

from .base import Service
from .registry import ServiceRegistry

User = get_user_model()

ServiceT = t.TypeVar("ServiceT", bound=Service)


class Environment:
    """What every service of a single unit of work shares: the acting user, the
    language, the timezone and a context, plus lazily built service instances.

    One environment per request (or per script / per test). Instances are *not*
    deduplicated across environments: sharing them would also share the mutable
    context between concurrent requests of the same user.

    Subscripting is offered for convenience but this is deliberately not a
    `Mapping`: `get()` takes a service class, not a key with a default, so the
    mapping contract would be violated.
    """

    user: t.Optional[User]
    language: t.Optional[str]
    tz: t.Optional[str]
    context: t.Optional[dict]

    registry: ServiceRegistry = ServiceRegistry

    def __init__(self, user=None, language=None, tz=None, context: dict | None = None):
        self.user = user
        self.language = language if language is not None else settings.LANGUAGE_CODE
        self.tz = tz if tz is not None else settings.TIME_ZONE
        # Read-only view: a shared mutable context is how one request ends up
        # observing another's values.
        self.context = MappingProxyType(dict(context or {}))

        # Both dicts are assigned once and only ever mutated in place, so
        # `__setattr__` can keep every public attribute read-only.
        self._services = {}
        self._cache = {}

    def __setattr__(self, name: str, value: t.Any) -> None:
        # once initialized, attributes are read-only
        if name in vars(self):
            raise AttributeError(f"Attribute {name!r} is read-only, call `env()` instead")
        return super().__setattr__(name, value)

    #
    # Service access
    #

    def __contains__(self, model) -> bool:
        """ Test whether a service exists for the given model class. """
        return self.registry.contains(model)

    def __getitem__(self, model: t.Type[Model]) -> Service:
        """ Return the service serving the given model class.

        This is the door for *generic* code, which only knows model classes it
        discovered by introspection. Business code should prefer `get()`, which
        keeps the precise type.
        """
        service_class = self.registry.get_service_class(model)
        if service_class is None:
            label = getattr(getattr(model, "_meta", None), "label", model)
            raise KeyError(f"No service registered for {label!r}")
        return self.get(service_class)

    def get(self, service_class: t.Type[ServiceT]) -> ServiceT:
        """ Return the instance of the given service class, building it once per environment.

        Instantiation is lazy and cached, which both breaks dependency cycles
        between services and guarantees a single instance per unit of work.
        """
        if service_class not in self._services:
            self._services[service_class] = service_class(self)
        return self._services[service_class]

    def __iter__(self):
        """ Return an iterator on the served model classes. """
        return iter(self.registry.keys())

    def __len__(self):
        """ Return the number of served models. """
        return len(self.registry.keys())

    def __eq__(self, other):
        return self is other

    def __ne__(self, other):
        return self is not other

    def __hash__(self):
        return object.__hash__(self)

    def __call__(
        self,
        user: t.Optional[User] = None,
        language: t.Optional[str] = None,
        tz: t.Optional[str] = None,
        context: dict | None = None,
    ) -> "Environment":
        """ Return a new environment, defaulting to the current values.

        Omitting an argument keeps what this environment holds; it does not reset
        it. A fresh environment starts with an empty service cache, which is what
        makes a context switch actually take effect.
        """
        return Environment(
            user=self.user if user is None else user,
            language=self.language if language is None else language,
            tz=self.tz if tz is None else tz,
            context=dict(self.context) if context is None else context,
        )

    #
    # Access rules
    #

    async def get_access_roles(self) -> list:
        """ Roles of the acting user, fetched at most once per environment.

        Access rules are evaluated on every read, and resolving a relation goes
        through the related service's own rule check. Without this memoization,
        writing a record with two relations would pay one extra role query per
        relation.
        """
        if "access_roles" not in self._cache:
            roles = []
            if self.user:
                roles = [role async for role in self.user.roles.all()]
            self._cache["access_roles"] = roles
        return self._cache["access_roles"]
