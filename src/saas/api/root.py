from ninja import NinjaAPI

__all__ = ["saas_api"]

# The API of the operator of the platform, apart from the API of the tenants
# (`api_v1`): another audience, another authentication (`SaasApiKey`), and no
# place in the documentation the tenants read. Its own documentation is in
# `docs/saas.md`: not served, so as not to reveal the API.
saas_api = NinjaAPI(
    version="1",
    urls_namespace="saas",
    title="Totem SaaS API",
    docs_url=None,
    openapi_url=None,
)
