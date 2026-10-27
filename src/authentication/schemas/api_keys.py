from typing import Optional

from ninja import FilterSchema
from pydantic import Field

from core.schemas import ModelSchema
from authentication.models import ApiKey

# ----------------------------------------------------
# API Schemas
# ----------------------------------------------------


class ApiKeyDisplayNameSchema(ModelSchema):
    class Meta:
        model = ApiKey
        fields = ["id", "name"]


class ApiKeySchema(ModelSchema):
    class Meta:
        model = ApiKey
        fields = ["id", "name", "scope", "is_active", "expires_at", "created_at"]
        optional_fields = "__all__"


class ApiKeyCreateSchema(ModelSchema):
    """ `scope` is required and has no default here, mirroring
    `ApiKeyQuerySet.create_with_secret`: granting nothing has to be said, by
    passing `[]`.

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


# No update schema, and no `secret_hash` anywhere above. The first because
# `ApiKeyService` composes no `UpdateMixin` -- a secret is not edited, it is
# revoked and replaced, and widening the scopes of a key already in circulation
# would be a silent privilege escalation. The second because the hash is a
# credential derivative that nothing outside the authenticator needs to read.
