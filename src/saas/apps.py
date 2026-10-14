from django.apps import AppConfig


class SaasConfig(AppConfig):
    """ Operation of a multi-tenant platform: the creation of tenant databases
    (`/saas/tenant-create/`) and their migration (`tenant_migrate`). No model:
    the catalog of tenants belongs to the proxy for now.

    Always installed: `tenant_migrate --all` also migrates the single database
    of a single-tenant deployment.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "saas"
