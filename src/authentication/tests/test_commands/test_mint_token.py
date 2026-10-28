import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from authentication.tokens import decode_access_token
from user.models import User, UserRole


class MintTokenCommandTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.role = UserRole.objects.create(
            pk="MINTER", name="Minter", permissions=["totem.country.read"]
        )
        cls.user = User.objects.create(username="bilbo", email="bilbo@example.com")
        cls.user.roles.add(cls.role)

    def mint(self, *args, **options):
        """ Run the command and return what it printed on stdout.

        stderr is captured too and dropped: the token is on stdout alone, so a
        shell can capture it without parsing, and this asserts that it stays
        that way.
        """
        stdout = io.StringIO()
        call_command("mint_token", *args, stdout=stdout, stderr=io.StringIO(), **options)
        return stdout.getvalue().strip()

    def test_the_token_decodes_and_carries_the_user(self):
        claims = decode_access_token(self.mint("bilbo"))

        self.assertEqual(claims["sub"], str(self.user.pk))
        self.assertEqual(claims["typ"], "access")

    def test_the_scopes_default_to_those_of_the_roles(self):
        claims = decode_access_token(self.mint("bilbo"))

        self.assertEqual(claims["scope"], "totem.country.read")

    def test_scopes_can_be_narrowed(self):
        # The point of the option: reproducing a 403 without editing a role.
        claims = decode_access_token(self.mint("bilbo", scopes="totem.user.read"))

        self.assertEqual(claims["scope"], "totem.user.read")

    def test_an_unregistered_scope_is_accepted(self):
        # Deliberately not validated: `TokenHasScopePermission` compares strings,
        # so an unknown scope grants nothing, which is a useful thing to mint.
        claims = decode_access_token(self.mint("bilbo", scopes="totem.nope.read"))

        self.assertEqual(claims["scope"], "totem.nope.read")

    def test_an_unknown_user_is_an_error(self):
        with self.assertRaises(CommandError):
            self.mint("gollum")

    @override_settings(DEBUG=False)
    def test_a_long_lifetime_is_refused_outside_debug(self):
        # An access token is never looked up, so it cannot be revoked: a 30-day
        # one handed out from a production shell has no way back.
        with self.assertRaises(CommandError):
            self.mint("bilbo", ttl_days=30)

    @override_settings(DEBUG=False)
    def test_a_day_is_allowed_outside_debug(self):
        self.assertTrue(self.mint("bilbo", ttl_days=1))

    @override_settings(DEBUG=True)
    def test_a_long_lifetime_is_allowed_in_debug(self):
        claims = decode_access_token(self.mint("bilbo", ttl_days=30))

        self.assertGreater(claims["exp"] - claims["iat"], 29 * 24 * 3600)
