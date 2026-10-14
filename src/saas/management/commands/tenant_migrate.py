from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import DEFAULT_DB_ALIAS

from core.db.tenancy import tenant_databases, use_database


class Command(MigrateCommand):
    """ `migrate`, on the given tenant database, or on all of them.

    Same arguments and options as `migrate`, preceded by the database name (or
    `--all`, for every active tenant). `default` follows that database for the
    whole run, post-migrate handlers included, so `--database` can only stay
    `default`.

    Rejected alternative: a `--tenant` option on every command, through a
    global hook in `manage.py`. Each command that must run per database gets
    its own explicit entry point instead.
    """

    help = "Updates the schema of the given tenant database. " + MigrateCommand.help

    def add_arguments(self, parser):
        # First, so it is the first positional argument, before `migrate`'s.
        parser.add_argument("db_name", nargs="?", help="Name of the tenant database to migrate.")
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all_databases",
            help="Migrate the database of every active tenant, one after the other.",
        )
        parser.add_argument(
            "--remove-stale-contenttypes",
            action="store_true",
            help="Then delete the content types of the models that no longer exist (no prompt).",
        )
        super().add_arguments(parser)

    def handle(self, *args, **options):
        if options["database"] != DEFAULT_DB_ALIAS:
            raise CommandError("--database is not supported: the database is the `db_name` argument.")
        db_name = options.pop("db_name")
        all_databases = options.pop("all_databases")
        remove_stale = options.pop("remove_stale_contenttypes")
        if bool(db_name) == all_databases:
            raise CommandError("Give either a database name or --all.")

        for name in tenant_databases() if all_databases else [db_name]:
            if all_databases and options["verbosity"] >= 1:
                self.stdout.write(self.style.MIGRATE_HEADING(f"Database {name}:"))
            with use_database(name):
                super().handle(*args, **options)
                if remove_stale:
                    call_command(
                        "remove_stale_contenttypes",
                        interactive=False,
                        verbosity=options["verbosity"],
                    )
