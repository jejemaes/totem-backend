"""Background jobs run on the database of the unit of work that sent them.

The database travels in the `db_name` header of the task message: set on
publication from the current database (`before_task_publish`), and selected
again by the worker around the task (`TenantTask`). A task sent from a request,
from another task or by beat thus runs on the database it was sent for, with no
argument to pass along.

Rejected alternative: a `db_name` argument on each task. Every caller would have
to pass it, and forgetting it silently runs the task on the default database.
"""
from celery import Task
from celery.signals import before_task_publish

from core.db.tenancy import current_database, use_database

DB_NAME_HEADER = "db_name"


@before_task_publish.connect(dispatch_uid="core.celery.add_db_name_header")
def add_db_name_header(headers=None, **kwargs):
    """ Stamp the current database on each task message, unless already set
    (`apply_async(headers={"db_name": ...})` targets another database). """
    if headers is not None:
        headers.setdefault(DB_NAME_HEADER, current_database())


class TenantTask(Task):
    """ Runs the task on the database named by its message.

    The default task class of the app: `@shared_task` needs nothing more. A
    task called directly (`task()`, or eagerly) has no message: it stays on the
    database of its caller.
    """

    def __call__(self, *args, **kwargs):
        db_name = self.message_db_name()
        if db_name is None:
            return super().__call__(*args, **kwargs)
        with use_database(db_name):
            return super().__call__(*args, **kwargs)

    def message_db_name(self):
        request = self.request
        # The worker puts the message headers on the request; `apply()` keeps
        # the headers it is given under `headers`.
        db_name = getattr(request, DB_NAME_HEADER, None)
        if db_name is None:
            db_name = (getattr(request, "headers", None) or {}).get(DB_NAME_HEADER)
        return db_name
