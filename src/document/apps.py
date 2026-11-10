from django.apps import AppConfig


class DocumentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "document"
    verbose_name = "Documents"

    populate_dependencies = ["user"]  # the roles are `user.userrole` records
    populate_fixtures = ["user_roles"]
