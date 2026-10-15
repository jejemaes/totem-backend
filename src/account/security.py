from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.account.create", "Create Accounts", is_public=True)
register_permission("totem.account.read", "Read Accounts", is_public=True)
register_permission("totem.account.update", "Update Accounts", is_public=True)
register_permission("totem.account.delete", "Delete Accounts", is_public=True)

register_permission("totem.accountcategory.create", "Create Account Categories", is_public=True)
register_permission("totem.accountcategory.read", "Read Account Categories", is_public=True)
register_permission("totem.accountcategory.update", "Update Account Categories", is_public=True)
register_permission("totem.accountcategory.delete", "Delete Account Categories", is_public=True)

register_permission("totem.accountmovement.create", "Create Account Movements", is_public=True)
register_permission("totem.accountmovement.read", "Read Account Movements", is_public=True)
register_permission("totem.accountmovement.update", "Update Account Movements", is_public=True)
register_permission("totem.accountmovement.delete", "Delete Account Movements", is_public=True)

# No access rule: whoever holds a scope reaches every account.
