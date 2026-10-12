from django.core.management.base import CommandError
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import DEFAULT_DB_ALIAS

from core.db.tenancy import use_database


class Command(MigrateCommand):
    """ `migrate`, on the given tenant database.

    Same arguments and options as `migrate`, preceded by the database name.
    `default` follows that database for the whole run, post-migrate handlers
    included, so `--database` can only stay `default`.

    Rejected alternative: a `--tenant` option on every command, through a
    global hook in `manage.py`. Each command that must run per database gets
    its own explicit entry point instead.
    """

    help = "Updates the schema of the given tenant database. " + MigrateCommand.help

    def add_arguments(self, parser):
        # First, so it is the first positional argument, before `migrate`'s.
        parser.add_argument("db_name", help="Name of the tenant database to migrate.")
        super().add_arguments(parser)

    def handle(self, *args, **options):
        if options["database"] != DEFAULT_DB_ALIAS:
            raise CommandError("--database is not supported: the database is the `db_name` argument.")
        db_name = options.pop("db_name")
        with use_database(db_name):
            return super().handle(*args, **options)
