

class ServiceRegistry:
    _services = {}

    @classmethod
    def register(cls, service_class):
        cls._services[service_class.name] = service_class

    @classmethod
    def get_service_class(cls, name):
        return cls._services.get(name)

    @classmethod
    def contains(cls, name):
        return name in cls._services