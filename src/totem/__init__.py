# Installs the tenant connection handler: before anything can reach the
# database, as `connections["default"]` must already follow the current tenant.
import core.db.tenancy  # noqa: F401

# Load the Celery app with Django, so `@shared_task` binds to it and
# `delay()` publishes on the configured broker.
from .celery import app as celery_app

__all__ = ("celery_app",)
