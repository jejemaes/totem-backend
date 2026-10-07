import json


def ensure_periodic_task(name, task, crontab, kwargs=None, enabled=True, description=""):
    """Create the periodic task `name` running `task` on the `crontab` schedule,
    unless a periodic task with that name already exists.

    The schedules live in the database (`django_celery_beat`) so they can be
    changed from the admin: an existing task is never updated, or a `populate`
    would revert the schedule an administrator chose.

    :param crontab: dict of `CrontabSchedule` fields (`minute`, `hour`,
        `day_of_week`, `day_of_month`, `month_of_year`), the missing ones
        defaulting to `*`.
    :returns: the `PeriodicTask` and whether it was created.
    """
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    periodic_task = PeriodicTask.objects.filter(name=name).first()
    if periodic_task:
        return periodic_task, False

    schedule, dummy = CrontabSchedule.objects.get_or_create(**crontab)
    periodic_task = PeriodicTask.objects.create(
        name=name,
        task=task,
        crontab=schedule,
        kwargs=json.dumps(kwargs or {}),
        enabled=enabled,
        description=description,
    )
    return periodic_task, True
