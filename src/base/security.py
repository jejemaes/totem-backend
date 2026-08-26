from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.country.read", "Read Countries", is_public=True)
