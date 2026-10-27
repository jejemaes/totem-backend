from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone

from authentication.principal import ScopedPrincipalMixin
from authentication.tokens import generate_secret, hash_secret
from core.orm.fields import ULIDField
from core.orm.validators import validate_unique_choice_array
from user.access_rights import get_public_permission


class ApiKeyQuerySet(models.QuerySet):

    def bulk_create(self, objs, *args, **kwargs):
        """ Mint the secret of every key that comes without one, and keep the
        clear text on the instance for the response that returns it.

        Derived here and not in `ApiKeyService.validate_data`, for the two
        reasons that put the other derivations of this project on the queryset:
        the hook runs before the instance exists, and the service write path never
        calls `Model.save()`. Every writer that can hand the secret back goes
        through here -- the service, `create_with_secret`, the management command.
        The admin cannot create a key at all, and `ApiKeyAdmin` says why.
        """
        objs = list(objs)
        for obj in objs:
            if obj.secret_hash:
                continue  # explicitly provided by the caller
            secret = generate_secret()
            obj.secret_hash = hash_secret(secret)
            # Not a field: the clear secret is never stored. It lives on the
            # instance just long enough for `ApiKeyCreatedSchema` to read it.
            obj.secret = secret
        return super().bulk_create(objs, *args, **kwargs)

    def create_with_secret(self, name, scope, **kwargs):
        """ Create a key and return `(instance, secret)`, the clear secret once.

        `scope` is positional and mandatory, with no default: a key that silently
        came into existence with the scopes of whoever created it would be a
        privilege escalation waiting to happen. Granting nothing is a deliberate
        choice the caller has to make, by passing `[]`.
        """
        instance = self.model(name=name, scope=scope, **kwargs)
        self.bulk_create([instance])
        return instance, instance.secret

    def usable(self, now=None):
        """ The keys that may authenticate a request right now. """
        now = now or timezone.now()
        return self.filter(is_active=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )


class ApiKey(ScopedPrincipalMixin, models.Model):
    """ A machine-to-machine credential of the tenant.

    Mixin first in the MRO, and it is no `Model`, so this stays a single table:
    what it brings is the `request.auth` contract (`user is None`, `scopes`,
    `has_scopes`), which is why the authenticator can return the row itself
    instead of wrapping it.

    Not to be confused with `saas.security.SaasApiKey`, which checks the single
    key of the *operator* of the platform against a setting, on another
    `NinjaAPI` and for another audience. Same header name, different API object,
    no conflict.
    """

    # Set by `ApiKeyQuerySet.bulk_create` on a freshly minted key, and read by
    # `ApiKeyCreatedSchema`. Always `None` on a key loaded from the database.
    secret = None

    id = ULIDField("ID", primary_key=True)
    name = models.CharField(
        "Name",
        max_length=255,
        null=False,
        blank=False,
        unique=True,
        help_text="What this key is for. Unique, so it can be named in an operational runbook.",
    )
    secret_hash = models.CharField(
        "Secret Hash",
        max_length=64,
        null=False,
        blank=False,
        # As for `RefreshToken.secret_hash`: the unique constraint is the index
        # the authenticator looks the key up by.
        unique=True,
        help_text=(
            "SHA-256 of the secret, hex. The secret itself is returned once, when the key "
            "is created, and is never stored."
        ),
    )
    scope = ArrayField(
        models.CharField(max_length=128, blank=False, choices=get_public_permission),
        verbose_name="Scopes",
        blank=True,
        default=list,
        validators=[validate_unique_choice_array],
        help_text=(
            "Permissions this key may exercise. Empty by default: a new key can do nothing "
            "until scopes are granted explicitly."
        ),
    )
    is_active = models.BooleanField(
        "Active",
        default=True,
        help_text="Unset to revoke the key without deleting it, keeping the name taken.",
    )
    expires_at = models.DateTimeField(
        "Expiration",
        null=True,
        blank=True,
        help_text="Optional: a key without one never expires.",
    )
    created_at = models.DateTimeField("Created on", auto_now_add=True)

    objects = ApiKeyQuerySet.as_manager()

    class Meta:
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self):
        return self.name

    @property
    def scopes(self):
        return set(self.scope or [])
