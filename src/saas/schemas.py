from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from ninja import Schema
from pydantic import ConfigDict, EmailStr, Field, field_validator


class TenantCreateSchema(Schema):
    """ The database is the one the domain of the request designates (the
    `X-Tenant-Db` header of the proxy), not part of the body. """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr = Field(description="Email of the administrator, also their login.")
    name: str = Field(min_length=1, max_length=128, description="Name of the tenant, given to its website.")
    password: str = Field(min_length=1, description="Password of the administrator.")

    @field_validator("password")
    @classmethod
    def check_password(cls, value):
        # The policy of the settings (`AUTH_PASSWORD_VALIDATORS`), checked
        # here: the administrator is created before anyone could change it.
        try:
            validate_password(value)
        except ValidationError as exc:
            raise ValueError(" ".join(exc.messages)) from exc
        return value


class TenantSchema(Schema):
    dbname: str
    name: str
    email: str


class TenantMigrateSchema(Schema):
    """ The database is the one the domain of the request designates. """

    model_config = ConfigDict(extra="forbid")

    kill_connections: bool = Field(
        default=False,
        description="Terminate the sessions open on the database before migrating.",
    )


class TenantMigrationSchema(Schema):
    dbname: str
    killed_connections: int = Field(description="Sessions terminated before migrating.")
    applied: list[str] = Field(description="Migrations applied, as `app.name`.")
