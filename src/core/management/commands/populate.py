import importlib.util
import textwrap
from argparse import RawTextHelpFormatter

from django.apps import apps
from django.core import management
from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS, connections, transaction

from core.db.tenancy import use_database
from core.utils.topological_sort import stable_topological_sort

ENV_LIST = ["system", "local"]


class Command(BaseCommand):
    help = textwrap.dedent(
        """
        Populate database with generated/imported data

        Purpose is to generate data to populate the database and have a set of data ready to
        test some flow, monitor the charge, ...

        To use that, your `AppConfig` of django app should have the `populate_dependencies`
        attribute (list of django apps dependencies) and `populate_fixtures` attribute (list
        of allowed fixture names).
        The `AppConfig` can also implement the `populate_<env>` method to alter or generate
        data.

        Some option of the command are protected, depending on the `ENVIRONMENT_NAME` env
        variable (`local`, `dev`, `staging`, `prod`).
    """
    )

    _dependency_map = None

    def create_parser(self, prog_name, subcommand):
        parser = super(Command, self).create_parser(prog_name, subcommand)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_arguments(self, parser):
        parser.add_argument(
            "apps", nargs="*", type=str, help="Specific django app labels to populate"
        )
        parser.add_argument(
            "--env",
            choices=ENV_LIST,
            dest="env",
            default='local',
            help="Environment from which to load the fixtures.",
        )
        parser.add_argument(
            "--size",
            default="small",
            choices=["small", "medium", "big"],
            type=str,
            help="Size of item to generate, in term of quantity. Only for apps implementing that param.",
        )
        parser.add_argument(
            "--drop-db",
            "--plouf-db",
            action="store_true",
            dest="drop_db",
            help="Force to drop the database (data and schema) and recreate it by running migrations. Requires the `django-extensions` to be installed to drop the schema, otherwise only the data will be removed.",
        )
        parser.add_argument(
            "--db-name",
            dest="db_name",
            default=None,
            help="Tenant database to populate. Defaults to the database of the settings.",
        )

    def handle(self, *args, **options):
        if options["db_name"]:
            with use_database(options["db_name"]):
                return self._handle(*args, **options)
        return self._handle(*args, **options)

    def _handle(self, *args, **options):
        # Determine which apps to process
        app_list = options["apps"]
        if not app_list:
            app_list = [app.label for app in apps.get_app_configs()]

        # Find dependency tree
        app_list = self.resolve_dependency_order(app_list)

        # Reset Database
        if options["drop_db"]:
            if options["apps"]:
                self.stdout.write(
                    "--drop-db' option can not be used with specific app name mentioned."
                )
                return

            self.stdout.write("Reseting database")
            try:
                self.db_reset()
            except Exception:
                self.stdout.write(
                    "Reseting database FAILED ! Flushing it instead....")
                management.call_command(
                    "flush",
                    "--noinput",
                    verbosity=options["verbosity"],
                )
            management.call_command("migrate", verbosity=options["verbosity"])

        # Force loading system env (must be first)
        env_list = [options['env']]
        if 'system' not in env_list:
            env_list = ['system'] + env_list

        # Populate (each env)
        for env in env_list:
            # Load fixtures
            for app_name in app_list:
                fixtures = []
                app_config = apps.get_app_config(app_name)
                fixtures = getattr(app_config, "populate_fixtures", [])
                if fixtures:
                    self.stdout.write(f"Loading fixture for {app_name} ...")
                else:
                    self.stdout.write(f"No fixtures for {app_name} ...")

                for fixture in fixtures:
                    try:
                        management.call_command(
                            "loaddata",
                            f"{env}/{fixture}",
                            verbosity=options['verbosity'],
                        )
                    except CommandError:
                        if options["verbosity"] >= 1:
                            self.stdout.write(
                                f"No fixture {env}/{fixture} found. Ignored."
                            )

            # Populate apps
            args = [
                options["size"],
            ]
            kwargs = {"drop_db": options["drop_db"]}

            with transaction.atomic():
                for app_name in app_list:
                    app_config = apps.get_app_config(app_name)
                    populate_method = getattr(
                        app_config, f"populate_{env}", None)
                    if populate_method:
                        self.stdout.write(f"Start populating {app_name} ...")
                        populate_method(*args, **kwargs)
            self.stdout.write(
                f"Database populated (size: {options['size']}, env: {env})"
            )
        self.stdout.write("Database completely populated. Done !")

    # Dependency Resolution

    @property
    def dependency_map(self):
        """Django application dependencies. `key` depends on the set of `values`
        :returns
            ```
            {
                "app1": set("app2"),
                "app2": set("app3", "app4"),
                "app3": set(),
                "app4": set(),
            }
            ```
        """
        if self._dependency_map is None:
            dependencies_map = {}
            for app_config in apps.get_app_configs():
                deps = getattr(app_config, "populate_dependencies", [])
                dependencies_map[app_config.label] = set(deps)
            self._dependency_map = dependencies_map
        return self._dependency_map

    def dep_resolve(self, app_name, resolved, unresolved):
        """Inspired from https://www.electricmonk.nl/docs/dependency_resolving_algorithm/dependency_resolving_algorithm.pdf"""
        unresolved.append(app_name)
        edges = self.dependency_map[app_name]
        for edge in edges:
            if edge not in resolved:
                if edge in unresolved:
                    raise Exception('Circular reference detected')
                self.dep_resolve(edge, resolved, unresolved)
        resolved.append(app_name)
        unresolved.remove(app_name)

    def resolve_dependency_order(self, app_list):
        # find dependencies for each given app name
        deps = set()
        for app_name in app_list:
            resolved = []
            unresolved = []
            self.dep_resolve(app_name, resolved, unresolved)
            deps |= set(resolved)

        # `deps` now contains all deps to explore, now topological sort will find the order
        # to explore them
        return stable_topological_sort(deps, self.dependency_map)

    # Database Trashing

    def db_reset(self):
        """ Drop and recreate the current database (see `use_database()`). """
        connection = connections[DEFAULT_DB_ALIAS]
        # The pool would otherwise keep connections to the dropped database.
        connection.close()
        connection.close_pool()
        dbinfo = connection.settings_dict

        database_name = dbinfo.get('NAME')
        database_host = dbinfo.get('HOST')
        database_port = dbinfo.get('PORT')
        user = dbinfo.get('USER')
        password = dbinfo.get('PASSWORD')
        owner = user
        if database_name == '':
            raise CommandError(
                "You need to specify DATABASE_NAME in your Django settings file."
            )

        has_psycopg3 = importlib.util.find_spec("psycopg")
        if has_psycopg3:
            import psycopg as Database  # NOQA
        else:
            import psycopg2 as Database  # NOQA

        # Connection to database server in order to remove the main database
        conn_params = {'dbname': 'template1'}
        if user:
            conn_params['user'] = user
        if password:
            conn_params['password'] = password
        if database_host:
            conn_params['host'] = database_host
        if database_port:
            conn_params['port'] = database_port

        connection = Database.connect(**conn_params)
        if has_psycopg3:
            connection.autocommit = True
        else:
            connection.set_isolation_level(0)  # autocommit false
        cursor = connection.cursor()

        # Force close connections
        close_sessions_query = (
            """
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '%s';
        """
            % database_name
        )
        self.stdout.write("Closing active connections...")
        try:
            cursor.execute(close_sessions_query)
        except Database.ProgrammingError as e:
            self.stdout.write("Error: %s" % (str(e),))

        # Drop the database
        drop_query = "DROP DATABASE \"%s\";" % database_name
        try:
            cursor.execute(drop_query)
        except Database.ProgrammingError as e:
            self.stdout.write("Error: %s" % (str(e),))

        create_query = "CREATE DATABASE \"%s\"" % database_name
        if owner:
            create_query += " WITH OWNER = \"%s\" " % owner
        create_query += " ENCODING = 'UTF8'"
        create_query += ';'

        self.stdout.write("Recreating database...")
        cursor.execute(create_query)
