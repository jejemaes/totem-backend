from django.dispatch import Signal

# Emitted on every rights change, and listened to by nothing since the OAuth
# toolkit went away. Its receiver used to delete the user's access tokens, which
# an access token with its scopes in a claim no longer needs: a rotation
# recomputes them from the live roles, so a change propagates on its own within
# one access token lifetime, with nobody signed out. Deactivating an account --
# the case that does need immediacy -- is handled on every request by `JWTAuth`,
# which loads the user with `is_active=True`.
#
# Kept because it is the right hook, and because what should listen to it is
# knowable: `RefreshTokenQuerySet.revoke_for_users` is one call away for a
# "sign out everywhere".
user_change_rights = Signal() # args: user_qs
