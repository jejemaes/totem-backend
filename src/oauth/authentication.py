import hashlib
from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.db.models.query import prefetch_related_objects
from django.http import HttpRequest
from ninja.security import HttpBearer

from oauth.models import AccessToken


class OAuthTokenAuthentication(HttpBearer):

    async def authenticate(self, request: HttpRequest, token: str):
        token_checksum = hashlib.sha256(token.encode("utf-8")).hexdigest()
        try:
            qs = AccessToken.objects.select_related("user")
            access_token = await sync_to_async(qs.get)(token_checksum=token_checksum)
            if access_token.is_valid():
                # Prefetching user roles is needed to compute scopes to set on the token. They'll be put
                # in cache, otherwise each time a `user.roles.all()` is done, a query is executed.
                await sync_to_async(prefetch_related_objects)(
                    [access_token.user], "roles"
                )

                return access_token

        except ObjectDoesNotExist:
            return
