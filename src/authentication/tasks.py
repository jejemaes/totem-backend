from celery import shared_task

from authentication.models import RefreshToken


@shared_task
def clear_tokens():
    """Remove the refresh tokens that can no longer be exchanged.

    Access tokens need no cleanup: they are stateless, so there is no row to
    remove -- a reduction this task is the visible half of.

    Idempotent, which `CELERY_TASK_ACKS_LATE` requires: a worker killed
    mid-task has its message redelivered. No `delay_on_commit`, since beat
    triggers it rather than a service, and `TenantDatabaseScheduler` runs it on
    every tenant database.
    """
    RefreshToken.objects.purge_expired()
