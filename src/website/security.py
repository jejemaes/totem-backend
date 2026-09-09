from django.db.models import Model, Q

from user.access_rights import register_permission
from user.access_policy import BaseRule
from website.models import Page

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

# `websitemedia` for the same reason as above, and more so: `media` is about as
# generic a name as exists. No `.update`: a media is immutable server-side, so
# MediaService exposes no update and no route would honour one.
register_permission("totem.websitemedia.create", "Create Website Medias", is_public=True)
register_permission("totem.websitemedia.read", "Read Website Medias", is_public=True)
register_permission("totem.websitemedia.delete", "Delete Website Medias", is_public=True)

# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------


class WebsiteManageOwnPageRule(BaseRule):
    identifier: str = "website_manage_own_page"
    model: Model = Page
    name: str = "Manage Own Page"
    description: str = "Manage only the Page you are author of."
    operations = ["create", "read", "update", "delete"]

    def scope_filter(self, context) -> Q:
        if context.user:
            return Q(user_id=context.user.pk)
        return Q()
