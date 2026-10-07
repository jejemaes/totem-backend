from celery import shared_task
from django.core.management import call_command


@shared_task
def clear_sessions():
    """Remove the expired sessions (django admin)."""
    call_command("clearsessions")


@shared_task
def clear_filestore():
    """Remove the empty directories of the filestore and the media stores."""
    call_command("clear_filestore", "--empty-dir")
