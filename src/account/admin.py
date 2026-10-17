from django.contrib import admin

from account.models import Account, AccountCategory, AccountMovement, Budget, BudgetLine, BudgetPosition

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


class BudgetPositionInline(admin.TabularInline):
    model = BudgetPosition
    fields = ("sequence", "category", "total_planned", "total_practical")
    readonly_fields = ("total_planned", "total_practical")
    extra = 0


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("name", "account", "user", "active", "total_planned_amount", "total_practical_amount")
    list_filter = ("active", "account")
    search_fields = ("name",)
    readonly_fields = ("total_planned_amount", "total_practical_amount")
    inlines = [BudgetPositionInline]


@admin.register(BudgetLine)
class BudgetLineAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "budget", "planned_amount", "sequence")
    list_filter = ("budget",)
    search_fields = ("name",)
