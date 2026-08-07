import functools
import typing

from .registry import ServiceRegistry

if typing.TYPE_CHECKING:
    from .environment import Environment


class ServiceMeta(type):
    def __new__(cls, name, bases, namespace):
        new_class = super().__new__(cls, name, bases, namespace)
        # `register` ignores services without a model: the registry is keyed by
        # model class, so only model-bound services are addressable.
        ServiceRegistry.register(new_class)
        return new_class


class Service(metaclass=ServiceMeta):

    model = None

    def __init__(self, env: "Environment"):
        self.env = env

    def with_context(self, **kwargs) -> "Service":
        """Return the same service on a new environment with the given context values updated."""
        context = dict(self.env.context)
        context.update(kwargs)
        return self.env(context=context).get(self.__class__)

    @functools.cached_property
    def user(self):
        return self.env.user

    @functools.cached_property
    def language(self):
        return self.env.language

    @functools.cached_property
    def tz(self):
        return self.env.tz

    @functools.cached_property
    def context(self):
        return self.env.context
