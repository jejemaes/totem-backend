import uuid

from django.db import models
from oauth2_provider.models import (
    AbstractAccessToken,
    AbstractApplication,
    AbstractGrant,
    AbstractIDToken,
    AbstractRefreshToken,
)


class OAuthApp(AbstractApplication):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, null=False, primary_key=True
    )

    class Meta:
        verbose_name = "OAuth Application"
        verbose_name_plural = "OAuth Applications"


class RefreshToken(AbstractRefreshToken):
    pass


class Grant(AbstractGrant):
    pass


class IDToken(AbstractIDToken):
    pass


# ------------------------------------------------
# Access Token
# ------------------------------------------------


class AccessToken(AbstractAccessToken):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, null=False, primary_key=True
    )
