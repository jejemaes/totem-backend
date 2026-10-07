from django.apps import AppConfig


class BaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "base"

    populate_fixtures = ["country"]

    def populate_system(self, size, **kwargs):
        from core.utils.celery import ensure_periodic_task

        ensure_periodic_task(
            "Clear expired sessions",
            "base.tasks.clear_sessions",
            crontab={"minute": "15", "hour": "3"},
        )
        ensure_periodic_task(
            "Clear empty filestore directories",
            "base.tasks.clear_filestore",
            crontab={"minute": "0", "hour": "4", "day_of_week": "0"},
        )
