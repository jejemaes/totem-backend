from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "authentication"

    # `authentication` rather than `auth` (taken by `django.contrib.auth`), and
    # rather than keeping the `oauth` label: a label with a migration history
    # already recorded in every existing database would have its regenerated
    # `0001_initial` considered applied, and the new tables would never be
    # created -- once per tenant database.
    populate_dependencies = ["user"]
