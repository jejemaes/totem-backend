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

# Read-only: the list of widget kinds comes from the code, so there is nothing
# to create, update or delete. `websitewidget` follows the convention above --
# and `widget` on its own is exactly the kind of name another app would claim.
register_permission("totem.websitewidget.read", "Read Website Widget Types", is_public=True)

# `totem.website.*`, not `totem.websitewebsite.*`: this is the one model where
# the `<app><model>` convention above folds in on itself. No `.create` and no
# `.delete` -- `WebsiteService` exposes neither, since the row is provisioned
# once by `populate_system`, and registering a scope nothing enforces is how a
# client learns to ask for a capability that does not exist.
register_permission("totem.website.read", "Read Website Settings", is_public=True)
register_permission("totem.website.update", "Update Website Settings", is_public=True)

# Read-only, like `websitewidget` and for the same reason: the list of themes and
# the layout vocabulary come from the code, so there is nothing to create, update
# or delete. A restricted author needs it exactly as much as an administrator --
# it is what populates the layout picker on a page.
register_permission("totem.websitetheme.read", "Read Website Themes", is_public=True)

# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------


# Nothing is registered for `Website`, and that is load-bearing rather than an
# omission: `apply_access_rules` leaves a queryset untouched only while its
# model has no rule, and the public render path reads the row as `user=None`
# with no role at all. The first `BaseRule` declared for `Website` would filter
# that read to nothing and blank every page of the site.


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
