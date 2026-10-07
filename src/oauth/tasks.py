from celery import shared_task
from django.core.management import call_command


@shared_task
def clear_tokens():
    """Remove the expired access and refresh tokens, and the expired grants."""
    call_command("cleartokens")
