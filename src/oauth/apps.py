import datetime
import uuid
from django.apps import AppConfig, apps
from django.utils import timezone

from oauth2_provider.scopes import get_scopes_backend


FRONTEND_CLIENT_ID = "HfklzFtWfWxubcc3UjbJrpNaMtffc9CrH7bw4yN7"


class OAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "oauth"

    def ready(self):
        from oauth import signals # noqa

    populate_dependencies = ["user"]
    populate_fixtures = ["oauth_app"]

    def populate_system(self, size, **kwargs):
        from core.utils.celery import ensure_periodic_task

        ensure_periodic_task(
            "Clear expired OAuth tokens",
            "oauth.tasks.clear_tokens",
            crontab={"minute": "0", "hour": "3"},
        )

    def populate_local(self, size, **kwargs):
        User = apps.get_model("user", "User")
        AccessToken = apps.get_model("oauth", "AccessToken")
        OAuthApp = apps.get_model("oauth", "OAuthApp")

        # User tokens
        users = User.objects.all().order_by('pk')

        # Frontend App (normally created in fixture system)
        application, dummy = OAuthApp.objects.get_or_create(
                client_id=FRONTEND_CLIENT_ID,
                defaults={
                    "name": "Frontend App",
                    "client_id": FRONTEND_CLIENT_ID,
                    "client_type": "public",
                    "authorization_grant_type": "password",
                    "skip_authorization": True,
                }
        )

        # Delete frontend tokens for existing users
        AccessToken.objects.filter(user__in=users, application=application).delete()

        tokens = []
        backend_scopes = get_scopes_backend()
        for index, user in enumerate(users):
            scopes = backend_scopes.get_user_scopes(user)
            tokens.append(
                AccessToken(
                    pk=uuid.UUID(int=index),
                    user=user,
                    token=f"user_token_{user.username}",
                    expires=timezone.now() + datetime.timedelta(days=365),
                    scope=" ".join(scopes),
                    application=application,
                )
            )

        AccessToken.objects.bulk_create(tokens)
