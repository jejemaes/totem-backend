import textwrap
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from authentication.tokens import encode_access_token
from core.db.tenancy import current_database, use_database
from user.access_rights import get_user_scopes
from user.models import User


class Command(BaseCommand):
    """ Print an access token for a user of the current tenant database.

    Replaces the `user_token_<username>` rows the OAuth fixtures used to seed: an
    access token is no longer a record, so there is nothing a fixture could hold.
    This mints one on demand instead, with the production encoder -- nothing
    about the format is reimplemented here, which is the point of the command
    existing at all rather than a snippet in the docs.
    """

    help = textwrap.dedent(
        """
        Mint an access token for a user, and print it.

        The token carries the name of the current database in its `db` claim, so
        it is only valid against the tenant it was minted on (see `--db-name`).
    """
    )

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Username of the user to mint a token for.")
        parser.add_argument(
            "--scopes",
            dest="scopes",
            default=None,
            help=(
                "Comma-separated scopes to freeze into the token. "
                "Defaults to every permission the user's roles grant."
            ),
        )
        parser.add_argument(
            "--ttl-days",
            dest="ttl_days",
            type=int,
            default=None,
            help="Lifetime in days, instead of the 15 minutes of a real token.",
        )
        parser.add_argument(
            "--db-name",
            dest="db_name",
            default=None,
            help="Tenant database to mint on. Defaults to the database of the settings.",
        )

    def handle(self, *args, **options):
        if options["db_name"]:
            with use_database(options["db_name"]):
                return self._handle(*args, **options)
        return self._handle(*args, **options)

    def _handle(self, *args, **options):
        ttl_days = options["ttl_days"]
        # A long-lived token is a development convenience, and it is exactly the
        # thing that must not be mintable on a production shell: it would hand
        # out a credential no rotation can shorten, since an access token is
        # never looked up and therefore cannot be revoked.
        if ttl_days is not None and ttl_days > 1 and not settings.DEBUG:
            raise CommandError("--ttl-days above 1 requires DEBUG.")

        user = User.objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError(f"No user named {options['username']} in {current_database()}.")

        if options["scopes"]:
            scopes = [scope.strip() for scope in options["scopes"].split(",") if scope.strip()]
        else:
            scopes = get_user_scopes(user)
        # Not checked against the registry, deliberately: `TokenHasScopePermission`
        # compares strings, and an unknown scope simply grants nothing. Refusing
        # one here would only make it harder to reproduce a 403.

        token, expires_at = encode_access_token(
            user.pk,
            scopes,
            ttl=timedelta(days=ttl_days) if ttl_days is not None else None,
        )
        self.stdout.write(token)
        if options["verbosity"] >= 1:
            self.stderr.write(f"user      {user.username} ({user.pk})")
            self.stderr.write(f"database  {current_database()}")
            self.stderr.write(f"expires   {expires_at.isoformat()}")
            self.stderr.write(f"scopes    {' '.join(scopes) or '(none)'}")
