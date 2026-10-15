from django.contrib import admin

from account.models import Account, AccountCategory, AccountMovement

# The admin writes through `Model.save()`, around the service layer: the business
# rules of `account.services` are not applied here, and the stored totals of an
# account go stale until `Account.objects.refresh_computed()`.


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "active", "total_debit", "total_credit", "balance")
    list_filter = ("active",)
    search_fields = ("code", "name")
    readonly_fields = ("total_debit", "total_credit", "balance")


@admin.register(AccountCategory)
class AccountCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "account", "color")
    search_fields = ("name",)


@admin.register(AccountMovement)
class AccountMovementAdmin(admin.ModelAdmin):
    list_display = ("date", "account", "name", "amount", "category", "reference")
    list_filter = ("account", "category")
    search_fields = ("name", "reference")
    date_hierarchy = "date"
