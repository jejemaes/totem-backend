from django.conf import settings

SAAS_DB_ALIAS = "saas_base"


class TenantRouter:
    """ Keeps the tenant schema out of the catalog database.

    `saas_base` holds the catalog of tenants, owned by the proxy for now: no
    app of this project migrates there. Every other alias is a tenant database.
    """

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if db == SAAS_DB_ALIAS and SAAS_DB_ALIAS in settings.DATABASES:
            return False
        return None
