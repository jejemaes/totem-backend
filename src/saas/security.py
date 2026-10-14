import hmac

from django.conf import settings
from django.http import Http404
from ninja.security import APIKeyHeader


class SaasApiKey(APIKeyHeader):
    """ The key of the operator of the platform, in the `X-Api-Key` header,
    matched against `SAAS_API_KEY`. Without that setting, the operator API does
    not exist: 404 rather than 401, so as not to reveal it. """

    param_name = "X-Api-Key"

    def authenticate(self, request, key):
        expected = settings.SAAS_API_KEY
        if not expected:
            raise Http404
        if key and hmac.compare_digest(key.encode(), expected.encode()):
            return True
        return None
