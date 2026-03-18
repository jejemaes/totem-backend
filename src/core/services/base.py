# pylint: disable=protected-access
"""
Usage Example:

```
# Example 
class MyService(BaseService):
    def my_method(self):
        print(f"MyService: User ID: {self.context.user}")
        other_service = self.services['OtherService']
        other_service.other_method()

class OtherService(BaseService):
    def other_method(self):
        print(f"OtherService: User ID: {self.context.user}")

#Usage
if __name__ == "__main__":
    user_context = ServiceContext(user=42)
    with ServiceEnvironment(user_context) as services:
        my_service = services['MyService']
        my_service.my_method()

        with my_service.with_context(user=43) as services2:
            my_other_service = services2['OtherService']
            my_other_service.other_method()
```

"""

import contextvars
from typing import Dict, Any, Optional

# context Variables to store the current user context
_current_context = contextvars.ContextVar('_current_context', default=None)
# Context Variable to store the cache of service instances
_service_instances = contextvars.ContextVar('_service_instances', default={})


class ServiceContext:
    
    def __init__(self, user: None, language: str = None, tz: str = None, **extras):
        self.user = user
        self.language = language
        self.tz = tz
        self._extras = extras

    def to_dict(self):
        return {
            "user": self.user,
            "language": self.language,
            "tz": self.tz,
            **self._extras
        }


class ServiceRegistry:
    _services = {}

    @classmethod
    def register(cls, service_class):
        print(f"Registering service: {service_class._name}")
        cls._services[service_class._name] = service_class

    @classmethod
    def get_service_class(cls, name):
        return cls._services.get(name)


class ServiceMeta(type):
    def __new__(cls, name, bases, namespace):
        new_class = super().__new__(cls, name, bases, namespace)
        if new_class._name != "__unkonwn__":
            ServiceRegistry.register(new_class)
        return new_class


class BaseService(metaclass=ServiceMeta):

    _name: str = "__unkonwn__"

    def __init__(self, context=None):
        self.context = context

    @property
    def services(self):
        instances = _service_instances.get()
        context = _current_context.get()

        class ServiceDict:
            def __getitem__(self, name):
                if name not in instances:
                    service_class = ServiceRegistry.get_service_class(name)
                    if service_class is None:
                        raise KeyError(f"Service {name} not found.")
                    instances[name] = service_class(context)
                return instances[name]

        return ServiceDict()

    def with_context(self, **kwargs):
        new_context = ServiceContext(**{**self.context.__dict__, **kwargs})
        return ServiceEnvironment(new_context)


class ServiceEnvironment:
    def __init__(self, user_context: ServiceContext):
        self.user_context = user_context

    def __enter__(self):
        _current_context.set(self.user_context)
        _service_instances.set({})

        class ServiceDict:
            def __getitem__(self, name):
                instances = _service_instances.get()
                if name not in instances:
                    service_class = ServiceRegistry.get_service_class(name)
                    if service_class is None:
                        raise KeyError(f"Service {name} not found.")
                    instances[name] = service_class(_current_context.get())
                return instances[name]

        return ServiceDict()

    def __exit__(self, exc_type, exc_val, exc_tb):
        _current_context.set(None)
        _service_instances.set({})


# Uncomment the following code to see an example of how to use the service framework, and run `python src/core/services/base.py` to test it.
# #  Example 
# class MyService(BaseService):
#     _name = "MyService"

#     def my_method(self):
#         print(f"MyService: User ID: {self.context.user}")
#         other_service = self.services['new.service']
#         other_service.other_method()

# class OtherService(BaseService):
#     _name = "new.service"
#     def other_method(self):
#         print(f"OtherService: User ID: {self.context.user}")

# # Usage
# if __name__ == "__main__":
#     user_context = ServiceContext(user=42)
#     with ServiceEnvironment(user_context) as services:
#         my_service = services['MyService']
#         my_service.my_method()

#         with my_service.with_context(user=43) as services2:
#             my_other_service = services2['new.service']
#             my_other_service.other_method()