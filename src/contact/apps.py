from django.apps import AppConfig


class ContactConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "contact"
    verbose_name = "Contacts"

    populate_dependencies = ["base"]  # the country FK must be populated first
    populate_fixtures = []
