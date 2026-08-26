from django.apps import AppConfig


class ContactConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contact"

    populate_dependencies = ["base"]  # the country FK must be populated first
    populate_fixtures = []
