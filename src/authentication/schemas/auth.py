from ninja import Schema
from pydantic import ConfigDict, Field

# ----------------------------------------------------
# Request Schemas
# ----------------------------------------------------


class TokenObtainSchema(Schema):
    """ Credentials exchanged for a token pair.

    No `client_id` and no `grant_type`, unlike the OAuth2 body this replaces: a
    public single-page application gains nothing from registering a client it
    cannot keep a secret for.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, description="Login of the user.")
    password: str = Field(min_length=1, description="Password of the user.")


class TokenRefreshSchema(Schema):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1, description="The refresh token last returned.")


# ----------------------------------------------------
# Response Schemas
# ----------------------------------------------------


class TokenPairSchema(Schema):
    """ What an exchange and a rotation both return.

    `expires_in` rather than an absolute expiry: the client's clock is not
    trusted, and a duration is what a refresh timer needs anyway.
    """

    access_token: str
    refresh_token: str = Field(
        description="Single use: exchanging it returns a new one and invalidates this one."
    )
    token_type: str = Field(description="Always 'Bearer'.")
    expires_in: int = Field(description="Lifetime of the access token, in seconds.")
    scope: str = Field(description="Space-separated permissions granted to the access token.")
