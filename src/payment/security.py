from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.paymentmethod.create", "Create Payment Methods", is_public=True)
register_permission("totem.paymentmethod.read", "Read Payment Methods", is_public=True)
register_permission("totem.paymentmethod.update", "Update Payment Methods", is_public=True)
register_permission("totem.paymentmethod.delete", "Delete Payment Methods", is_public=True)

# `/payment/payments/`. The routes of a document's payments hold the scopes of
# that document instead (`totem.invoice.update` for an invoice): none of these
# opens them.
register_permission("totem.payment.create", "Create Payments", is_public=True)
register_permission("totem.payment.read", "Read Payments", is_public=True)
register_permission("totem.payment.update", "Update Payments", is_public=True)
register_permission("totem.payment.delete", "Delete Payments", is_public=True)

# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------

# None: whoever holds a scope reaches every payment method and every payment.
