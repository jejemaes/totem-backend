from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "account"

    populate_dependencies = ["user"]  # the roles are `user.userrole` records
    populate_fixtures = ["user_roles"]
