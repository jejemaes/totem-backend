from typing import List, Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from authentication.models import ApiKey

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class ApiKeySchema(ModelSchema):
    """ `scope` is declared here as a plain list of strings, overriding what the
    model field would generate -- and that is the point.

    The `choices` of the array turn into a pydantic enum, which is right on the
    way in and wrong on the way out: a response schema is handed whatever the row
    holds, and a value outside the enum raises, which ninja answers with a 500.
    A row can hold one: `Model.objects.create()` and `bulk_create` run no
    validation, and a permission removed from the code -- an app deleted -- would
    orphan every key that was granted it. Strict output would then take the whole
    list endpoint down and make those keys unreadable *and* undeletable through
    the API, which is the worst possible way to surface a data problem.

    Validate input strictly, report output faithfully. `ApiKeyCreateSchema` keeps
    the enum, where it belongs.
    """

    scope: List[str] = Field(
        default_factory=list,
        description="Permissions this key may exercise.",
    )

    class Meta:
        model = ApiKey
        fields = ["id", "name", "scope", "is_active", "expires_at", "created_at"]
        optional_fields = "__all__"


class ApiKeyCreateSchema(ModelSchema):
    """ `scope` mirrors the model, so it may be omitted -- and defaults to the
    empty list.

    Which is the guarantee that matters: a key never comes into existence holding
    the scopes of whoever created it. `ApiKeyQuerySet.create_with_secret` is
    stricter and takes `scope` as a mandatory argument, because a caller writing
    Python has no body schema to default it for them.

    The `choices` of the model field become a pydantic enum on this schema, so an
    unregistered or non-public scope is refused here, as a 422 on the body, and
    never reaches the service. `totem.apikey.*` is registered `is_public=False`
    and is therefore absent from that enum by construction.
    """

    class Meta:
        model = ApiKey
        fields = ["name", "scope", "expires_at"]


class ApiKeyCreatedSchema(ApiKeySchema):
    """ The response to a creation, and the only one that carries the secret.

    `secret` is not an ORM value, which is why it may only live in this schema:
    the `?fields=` machinery resolves a response schema against
    `model._meta.get_field()`, and this is the one response that never goes
    through it. Same reasoning that keeps `Page.url` out of `PageSchema`.
    """

    secret: str = Field(
        description="The clear secret, shown once. It is not stored and cannot be shown again."
    )


# ----------------------------------------------------
# Filters Schemas
# ----------------------------------------------------


class ApiKeyFilterSchema(FilterSchema):
    name: Optional[str] = Field(
        None,
        q="name__icontains",
        title="Name",
        description="Search term in the key name.",
    )
    is_active: Optional[bool] = Field(
        None,
        title="Active",
        description="Keep only the active, or only the revoked, keys.",
    )


# Three schemas this module deliberately does not define.
#
# No `ApiKeyUpdateSchema`: `ApiKeyService` composes no `UpdateMixin` -- a secret
# is not edited, it is revoked and replaced, and widening the scopes of a key
# already in circulation would be a silent privilege escalation.
#
# No `ApiKeyDisplayNameSchema`, unlike every other resource here: that schema is
# what a *relation* to a record serializes to, and nothing relates to a key. It
# would exist only to be unused, and `ApiKeyController` registers no
# /display-name/ route to consume it.
#
# And no `secret_hash` in any of them: the hash is a credential derivative that
# nothing outside the authenticator has a reason to read.
