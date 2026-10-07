import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "totem.settings")

app = Celery("totem")

# Every `CELERY_*` Django setting configures Celery (`CELERY_BROKER_URL` ->
# `broker_url`, ...).
app.config_from_object("django.conf:settings", namespace="CELERY")

# Registers the `tasks` module of each installed app.
app.autodiscover_tasks()
