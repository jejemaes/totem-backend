import os

from celery import Celery

# Connects `before_task_publish` before anything can be published.
import core.celery  # noqa: F401

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "totem.settings")

# Each task runs on the database it was sent for (see `core.celery`).
app = Celery("totem", task_cls="core.celery:TenantTask")

# Every `CELERY_*` Django setting configures Celery (`CELERY_BROKER_URL` ->
# `broker_url`, ...).
app.config_from_object("django.conf:settings", namespace="CELERY")

# Registers the `tasks` module of each installed app.
app.autodiscover_tasks()
