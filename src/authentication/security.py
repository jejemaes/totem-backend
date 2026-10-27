from user.access_rights import register_permission

# ---------------------------------------------------------
# Define Scopes
# ---------------------------------------------------------

# `is_public=False`, and this is the one place in the project where that flag
# earns its keep: `is_public` means "selectable as the scope of a credential
# through the public API", and a key able to mint keys is a privilege escalation
# with extra steps. These three are granted through a role -- a human
# administrator -- never through an API key.
#
# Concretely: `ApiKey.scope` offers `get_public_permission()` as its choices, so
# these are precisely the permissions an API key cannot be given.
register_permission("totem.apikey.create", "Create API Keys", is_public=False)
register_permission("totem.apikey.read", "Read API Keys", is_public=False)
register_permission("totem.apikey.delete", "Delete API Keys", is_public=False)

# No `.update`: `ApiKeyService` composes no `UpdateMixin`, and registering a
# scope nothing enforces is how a client learns to ask for a capability that
# does not exist (same reasoning as `totem.website.*`).

# ---------------------------------------------------------
# Access rules
# ---------------------------------------------------------

# Nothing is registered for `ApiKey`, deliberately, as for `Website`: a key is
# global to the tenant and the scope is the whole barrier. Scoping keys to an
# owner would be a rule, and would need an ownership column first -- at which
# point the absence of a rule here is what makes that change visible.
#
# Note the consequence, which is documented on `ApiKeyAuth` as well: a request
# authenticated by a key has no user, `Environment.get_access_roles()` therefore
# returns `[]`, `apply_access_rules` assembles no lookup, and the queryset comes
# back unfiltered. A key holding `totem.user.read` reads every user of the
# tenant. That is coherent for a machine caller, and it is not what one guesses.
