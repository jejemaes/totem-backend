import textwrap

from django.core.management.base import BaseCommand, CommandError

from authentication.models import ApiKey
from core.db.tenancy import current_database, use_database
from user.access_rights import get_public_permission


class Command(BaseCommand):
    """ Create a machine-to-machine key and print its secret, once.

    There is no fixture for this and there will not be one: a fixture holding a
    key would be a credential in the repository. The key is created here, the
    clear secret crosses the terminal once, and only its hash is kept.
    """

    help = textwrap.dedent(
        """
        Create an API key on the current tenant database, and print its secret.

        The secret is shown once and never stored: lose it and the key has to be
        recreated.
    """
    )

    def add_arguments(self, parser):
        parser.add_argument("name", type=str, help="What the key is for. Unique.")
        parser.add_argument(
            "--scopes",
            dest="scopes",
            required=True,
            help=(
                "Comma-separated permissions the key may exercise. "
                "Mandatory, `--scopes ''` for a key that can do nothing."
            ),
        )
        parser.add_argument(
            "--db-name",
            dest="db_name",
            default=None,
            help="Tenant database to create the key on. Defaults to the database of the settings.",
        )

    def handle(self, *args, **options):
        if options["db_name"]:
            with use_database(options["db_name"]):
                return self._handle(*args, **options)
        return self._handle(*args, **options)

    def _handle(self, *args, **options):
        scopes = [scope.strip() for scope in options["scopes"].split(",") if scope.strip()]

        # Checked, unlike `mint_token`'s: `bulk_create` runs no field validation,
        # so an unknown scope would silently produce a key that can do nothing
        # and gives no clue why. Against the *public* permissions, not all of
        # them -- `totem.apikey.*` is registered `is_public=False` precisely so
        # that no key can mint keys, and a shell is not an exception to that.
        allowed = {permission for permission, _ in get_public_permission()}
        unknown = sorted(set(scopes) - allowed)
        if unknown:
            raise CommandError(
                "Not a permission an API key may hold: {}.\nAvailable: {}".format(
                    ", ".join(unknown), ", ".join(sorted(allowed))
                )
            )

        if ApiKey.objects.filter(name=options["name"]).exists():
            raise CommandError(f"A key named {options['name']} already exists.")

        instance, secret = ApiKey.objects.create_with_secret(options["name"], scopes)
        self.stdout.write(secret)
        if options["verbosity"] >= 1:
            self.stderr.write(f"key       {instance.name} ({instance.pk})")
            self.stderr.write(f"database  {current_database()}")
            self.stderr.write(f"scopes    {' '.join(scopes) or '(none)'}")
            self.stderr.write("The secret above is not stored: keep it now.")
