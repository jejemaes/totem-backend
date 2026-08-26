from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

register_permission("totem.contact.create", "Create Contacts", is_public=True)
register_permission("totem.contact.read", "Read Contacts", is_public=True)
register_permission("totem.contact.update", "Update Contacts", is_public=True)
register_permission("totem.contact.delete", "Delete Contacts", is_public=True)

register_permission("totem.contacttag.create", "Create Contact Tags", is_public=True)
register_permission("totem.contacttag.read", "Read Contact Tags", is_public=True)
register_permission("totem.contacttag.update", "Update Contact Tags", is_public=True)
register_permission("totem.contacttag.delete", "Delete Contact Tags", is_public=True)
