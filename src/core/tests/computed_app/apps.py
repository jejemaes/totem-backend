from django.apps import AppConfig


class ComputedAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.tests.computed_app"
    label = "computed_app"
