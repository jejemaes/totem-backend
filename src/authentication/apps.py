from django.apps import AppConfig, apps

# The two credentials of a local developer, side by side on purpose: "how do I
# authenticate against my dev instance" has one answer, in one file.
#
# Neither is a secret. They exist only on the `local` dataset, which
# `populate --env local` writes and which no deployment loads.
DEV_PASSWORD = "totem"
DEV_API_KEY_NAME = "Local Development"
DEV_API_KEY_SECRET = "dev-api-key-secret"


class AuthenticationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "authentication"

    # `authentication` rather than `auth` (taken by `django.contrib.auth`), and
    # rather than keeping the `oauth` label: a label with a migration history
    # already recorded in every existing database would have its regenerated
    # `0001_initial` considered applied, and the new tables would never be
    # created -- once per tenant database.
    populate_dependencies = ["user"]

    def populate_system(self, size, **kwargs):
        from core.utils.celery import ensure_periodic_task

        ensure_periodic_task(
            "Clear expired tokens",
            "authentication.tasks.clear_tokens",
            crontab={"minute": "0", "hour": "3"},
        )

    def populate_local(self, size, **kwargs):
        from authentication.tokens import hash_secret

        ApiKey = apps.get_model("authentication", "ApiKey")
        User = apps.get_model("user", "User")

        # Necessary, not cosmetic: `user/fixtures/local/user.json` carries a
        # pbkdf2 hash whose clear text nobody knows, so without this nobody can
        # log into a freshly populated database -- and logging in is now the
        # only way to obtain a token.
        #
        # Here rather than in `UserConfig.populate_local`, which does not exist:
        # the reason is the login flow, not the user record, and
        # `populate_dependencies` guarantees this runs after the users are
        # loaded. `bulk_update` rather than a `save()` each, as everywhere else.
        users = list(User.objects.all())
        for user in users:
            user.set_password(DEV_PASSWORD)
        User.objects.bulk_update(users, ["password"])

        # Idempotent the same way the OAuth token seeding was: drop and remint,
        # since both `name` and `secret_hash` are unique.
        ApiKey.objects.filter(name=DEV_API_KEY_NAME).delete()
        ApiKey.objects.bulk_create(
            [
                ApiKey(
                    name=DEV_API_KEY_NAME,
                    # Supplied, so `bulk_create` mints nothing: a printed random
                    # secret would be useless to a script written yesterday.
                    secret_hash=hash_secret(DEV_API_KEY_SECRET),
                    # Empty, like every key this project creates. It exists so
                    # the `X-Api-Key` path is reachable on a fresh database, not
                    # so it can do anything: a key that can act is one explicit
                    # step away, `./manage.py create_api_key <name> --scopes ...`.
                    scope=[],
                )
            ]
        )
