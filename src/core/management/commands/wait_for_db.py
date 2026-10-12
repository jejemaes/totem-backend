import time
import warnings

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    """Django command to pause execution until the database server is available.

    It waits for the server, not for a database: in a multi-tenant deployment
    the database named in the settings may deliberately not exist, so the
    connection goes to the maintenance database (`postgres`), as Django does
    to create the test databases.
    """

    def handle(self, *args, **kwargs):
        self.stdout.write("waiting for db ...")
        while True:
            try:
                # Getting the alias alone opens nothing: a query is needed.
                # While the server is down, Django warns on each attempt that
                # it falls back from `postgres` to the configured database.
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    with connections["default"]._nodb_cursor() as cursor:
                        cursor.execute("SELECT 1")
            except OperationalError:
                self.stdout.write("Database unavailable, waiting 1 second ...")
                time.sleep(1)
            else:
                self.stdout.write(self.style.SUCCESS("db available"))
                return
