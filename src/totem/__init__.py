# Load the Celery app with Django, so `@shared_task` binds to it and
# `delay()` publishes on the configured broker.
from .celery import app as celery_app

__all__ = ("celery_app",)
