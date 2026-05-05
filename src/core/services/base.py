import functools
import typing
from .registry import ServiceRegistry

if typing.TYPE_CHECKING:
    from .environment import Environment


class ServiceMeta(type):
    def __new__(cls, name, bases, namespace):
        new_class = super().__new__(cls, name, bases, namespace)
        if new_class.name != "__unknown__":
            ServiceRegistry.register(new_class)
        return new_class


class Service(metaclass=ServiceMeta):

    name = "__unknown__"

    def __init__(self, env: "Environment", args: tuple, kwargs: dict):
        self.env = env
        self.args = args
        self.kwargs = kwargs

    def with_context(self, **kwargs) -> "Service":
        """Return a new service instance with the given context values updated."""
        context = self.env.context.copy()
        context.update(kwargs)

        new_env = self.env(
            user=self.env.user,
            language=self.env.language,
            tz=self.env.tz,
            context=context,
        )
        return self.__class__(new_env, self.args, self.kwargs)

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
