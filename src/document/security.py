from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.document.create", "Create Documents", is_public=True)
register_permission("totem.document.read", "Read Documents", is_public=True)
register_permission("totem.document.update", "Update Documents", is_public=True)
register_permission("totem.document.delete", "Delete Documents", is_public=True)

register_permission("totem.documenttag.create", "Create Document Tags", is_public=True)
register_permission("totem.documenttag.read", "Read Document Tags", is_public=True)
register_permission("totem.documenttag.update", "Update Document Tags", is_public=True)
register_permission("totem.documenttag.delete", "Delete Document Tags", is_public=True)

register_permission("totem.documenttagcategory.create", "Create Document Tag Categories", is_public=True)
register_permission("totem.documenttagcategory.read", "Read Document Tag Categories", is_public=True)
register_permission("totem.documenttagcategory.update", "Update Document Tag Categories", is_public=True)
register_permission("totem.documenttagcategory.delete", "Delete Document Tag Categories", is_public=True)

# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------

# None: no notion of an owner or of sharing yet, whoever holds a scope reaches
# every record. `Document.user` is the person in charge, not an access boundary.
