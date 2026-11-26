from django.apps import AppConfig


class PaymentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payment"
    verbose_name = "Payments"

    populate_dependencies = ["user"]  # the roles are `user.userrole` records
    populate_fixtures = ["user_roles"]

    def ready(self):
        from payment import checks  # noqa: F401  registers the system checks
