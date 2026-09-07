from django.conf import settings

from core.services import Environment


class EnvironmentViewMixin:
    """Gives a plain django view the environment the API layer builds per request.

    The mirror of `core.api.request.Request.env`, for views that are not ninja
    routes: only routes are wrapped in `core.api.request.Request`
    (`core.api.route.Route`), so a `django.views.generic.base.View` has no
    `request.env` at all.

    A mixin rather than middleware: `core.api.request.Request` already builds an
    environment per API request, and a middleware would build a second one for
    every one of them -- while `Environment.__init__` does no I/O and its
    services are built lazily, so there is nothing to amortize.
    """

    @property
    def env(self) -> Environment:
        if not hasattr(self, "_env"):
            self._env = Environment(
                self.get_env_user(),
                language=settings.LANGUAGE_CODE,
                tz=settings.TIME_ZONE,
            )
        return self._env

    def get_env_user(self):
        """The acting user, or None for an anonymous visitor.

        `None`, never `AnonymousUser`: `user.access_policy.Context.user` is typed
        `Optional[User]` and would reject it, and `Environment.get_access_roles`
        would look for `.roles` on it. `user.access_policy.request_to_context`
        already forces `None` for the same reason.

        Deliberately not `request.user`: `AuthenticationMiddleware` installs a
        `SimpleLazyObject`, so evaluating it runs a session and a user query --
        synchronously, in the event-loop thread of an async view. Django 5.0's
        `await request.auser()` is the door to open if visitor authentication is
        ever needed.
        """
        return None
