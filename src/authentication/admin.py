from django.contrib import admin

from authentication.models import ApiKey


class ApiKeyAdmin(admin.ModelAdmin):
    """ List and revoke keys. Creating one here is deliberately not possible.

    A key is usable only if its clear secret reaches its holder, and the secret
    exists for exactly one moment -- `ApiKeyQuerySet.bulk_create` derives the hash
    and keeps the clear text on the instance, which the creation response reads.
    An admin form saves through `Model.save()`, which goes through no queryset, so
    it could only either store a key nobody can use or print a credential into a
    browser page and the admin log. Keys are created by the API
    (`POST /api/v1/api-keys/`) or by `./manage.py create_api_key`.

    `secret_hash` is read-only rather than hidden: an operator comparing a report
    against the stored digest is a legitimate thing to do, editing it is not.
    """

    list_display = ("name", "is_active", "expires_at", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("id", "secret_hash", "created_at")
    fields = ("id", "name", "secret_hash", "scope", "is_active", "expires_at", "created_at")

    def has_add_permission(self, request):
        return False


admin.site.register(ApiKey, ApiKeyAdmin)

# `RefreshToken` is deliberately not registered. It is a table of live session
# credentials with nothing an operator can act on one by one: revoking a session
# is `RefreshTokenQuerySet.revoke_session`, signing a user out everywhere is
# `revoke_for_users`, and the rows disappear on their own
# (`authentication.tasks.clear_tokens`).
