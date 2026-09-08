from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

# `websitepage` / `websitemenu` rather than the mechanical `page` / `menu`: both
# names are generic enough that another app could claim them, and the permission
# is what a client sees as an OAuth scope. It also matches the route prefix.
register_permission("totem.websitepage.create", "Create Website Pages", is_public=True)
register_permission("totem.websitepage.read", "Read Website Pages", is_public=True)
register_permission("totem.websitepage.update", "Update Website Pages", is_public=True)
register_permission("totem.websitepage.delete", "Delete Website Pages", is_public=True)

register_permission("totem.websitemenu.create", "Create Website Menu Items", is_public=True)
register_permission("totem.websitemenu.read", "Read Website Menu Items", is_public=True)
register_permission("totem.websitemenu.update", "Update Website Menu Items", is_public=True)
register_permission("totem.websitemenu.delete", "Delete Website Menu Items", is_public=True)
