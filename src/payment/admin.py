from django.contrib import admin

from payment.models import Payment, PaymentMethod


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("sequence", "code", "name", "type", "iban", "active")
    list_filter = ("type", "active")
    search_fields = ("code", "name", "iban")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Read-only: a payment written through `save()` would not book, rewrite or
    delete its account movement, which only `PaymentService` keeps in step."""

    list_display = ("date", "amount", "currency_code", "direction", "state", "payment_method", "contact", "invoice")
    list_filter = ("state", "direction", "payment_method", "target_type")
    search_fields = ("reference",)
    date_hierarchy = "date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
