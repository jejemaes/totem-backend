from django.conf import settings
from django.http import HttpRequest

from core.services import Environment


class Request:
    """
    Wrapper allowing to enhance a standard `HttpRequest` instance with additional
    properties and methods, such as the `env` property which provides access to
    the service environment.
    """

    def __init__(self, request):
        assert isinstance(request, HttpRequest), (
            'The `request` argument must be an instance of '
            '`django.http.HttpRequest`, not `{}.{}`.'
            .format(request.__class__.__module__, request.__class__.__name__)
        )

        self._request = request

    # Allow generic typing checking for requests.
    def __class_getitem__(cls, *args, **kwargs):
        return cls

    @property
    def content_type(self):
        meta = self._request.META
        return meta.get('CONTENT_TYPE', meta.get('HTTP_CONTENT_TYPE', ''))

    @property
    def env(self):
        if not hasattr(self, '_env'):
            self._env = Environment(
                self._get_request_user(),
                language=settings.LANGUAGE_CODE,
                tz=settings.TIME_ZONE,
            )
        return self._env

    def _get_request_user(self):
        user = None
        if hasattr(self._request, 'auth'):
            if hasattr(self._request.auth, 'user'):
                user = self._request.auth.user
        if user is None and hasattr(self._request, 'user'):
            user = self._request.user
        return user

    # @property
    # def user(self):
    #     """
    #     Returns the user associated with the current request, as authenticated
    #     by the authentication classes provided to the request.
    #     """
    #     if not hasattr(self, '_user'):
    #         with wrap_attributeerrors():
    #             self._authenticate()
    #     return self._user

    # @user.setter
    # def user(self, value):
    #     """
    #     Sets the user on the current request. This is necessary to maintain
    #     compatibility with django.contrib.auth where the user property is
    #     set in the login and logout functions.

    #     Note that we also set the user on Django's underlying `HttpRequest`
    #     instance, ensuring that it is available to any middleware in the stack.
    #     """
    #     self._user = value
    #     self._request.user = value

    # @property
    # def auth(self):
    #     """
    #     Returns any non-user authentication information associated with the
    #     request, such as an authentication token.
    #     """
    #     if not hasattr(self, '_auth'):
    #         with wrap_attributeerrors():
    #             self._authenticate()
    #     return self._auth

    # @auth.setter
    # def auth(self, value):
    #     """
    #     Sets any non-user authentication information associated with the
    #     request, such as an authentication token.
    #     """
    #     self._auth = value
    #     self._request.auth = value

    def __getattr__(self, attr):
        """
        If an attribute does not exist on this instance, then we also attempt
        to proxy it to the underlying HttpRequest object.
        """
        try:
            _request = self.__getattribute__("_request")
            return getattr(_request, attr)
        except AttributeError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{attr}'")
