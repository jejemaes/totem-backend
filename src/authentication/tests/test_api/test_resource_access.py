import json

from django.test import Client, TestCase
from ninja.utils import normalize_path
from parameterized import parameterized

from authentication.models import ApiKey
from authentication.tokens import hash_secret
from core.api.controller import BaseModelController
from core.testing import APITestCaseMixin
from totem.api import api_v1
from user.tests.test_api.common import CommonTestMixin

# A syntactically valid id that matches no record, so an endpoint can be reached
# without a fixture for its resource. See the docstring of the test case.
DUMMY_ID = "01ARZ3NDEKTSV4RRFFQ69G5FAV"

# The one resource no API key may read, because `totem.apikey.*` is registered
# `is_public=False` and so cannot be granted to a key at all. Swept for user
# tokens like every other, and asserted *unreachable* by key below, rather than
# skipped: "a key cannot manage keys" is the property, so it gets an assertion.
KEY_FORBIDDEN = {"ApiKeyController"}


def _walk(base, seen=None):
    seen = seen if seen is not None else set()
    for subclass in base.__subclasses__():
        if subclass not in seen:
            seen.add(subclass)
            yield subclass
        yield from _walk(subclass, seen)


def model_controllers():
    """ The model controllers of the tenant API.

    `core.tests.computed_app` is excluded: its controllers exist to exercise the
    framework layer with models of their own, carry no `permission_map`, and are
    installed only under the test runner. Sweeping them would assert things about
    scaffolding.
    """
    for controller in sorted(_walk(BaseModelController), key=lambda cls: cls.__name__):
        if getattr(controller, "api", None) is not api_v1:
            continue
        if getattr(controller, "model", None) is None:
            continue
        if controller.__module__.startswith("core.tests"):
            continue
        yield controller


def read_endpoints():
    """ `(name, url, scopes)` for the read route of every model controller.

    The list route when there is one, the retrieve route otherwise -- a singleton
    like `WebsiteController` publishes no list. Path parameters, which a nested
    prefix carries (`/budget/{budget_id}/lines/`), are filled with `DUMMY_ID`.
    """
    endpoints = []
    for controller in model_controllers():
        scopes = getattr(controller, "permission_map", {}).get("read")
        if not scopes:
            continue
        path = "/" if "list" in controller.__dict__ else f"/{DUMMY_ID}/"
        url = "/api/v1" + normalize_path(controller.path_prefix + path)
        url = url.replace("{budget_id}", DUMMY_ID)
        endpoints.append((controller.__name__, url, scopes))
    return endpoints


READ_ENDPOINTS = read_endpoints()
KEY_ENDPOINTS = [row for row in READ_ENDPOINTS if row[0] not in KEY_FORBIDDEN]


class ResourceApiKeyAccessTest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ Every resource endpoint accepts an API key, and honours its scopes.

    Exactly one thing is per-resource here: whether the controller's `auth` lists
    `ApiKeyAuth` at all. It was put there mechanically, across seventeen files at
    once, and a controller left out would answer 401 to every machine caller while
    its own suite -- which authenticates with a JWT -- stayed green. So the test
    is a sweep, like the risk.

    Built from the controller registry rather than a hand-written list, so a
    resource added later is covered without anyone remembering to add it.

    The assertions are on what a *credential* decides, not on what a resource
    returns: 200 or 404 both prove the key was accepted and its scope honoured,
    and accepting either is what lets the sweep run without a fixture per
    resource. What each resource returns is its own suite's job.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.key_without_scope = "a-key-that-can-do-nothing"
        ApiKey.objects.create(
            name="Scopeless",
            secret_hash=hash_secret(cls.key_without_scope),
            scope=[],
        )

    def key_with(self, scopes):
        secret = "scoped-" + "-".join(scopes)
        ApiKey.objects.create(
            name=f"Scoped {','.join(scopes)}",
            secret_hash=hash_secret(secret),
            scope=list(scopes),
        )
        return secret

    @parameterized.expand(KEY_ENDPOINTS)
    def test_a_scoped_key_is_accepted(self, name, url, scopes):
        response = self.do_api_key_request(url, "GET", self.key_with(scopes))

        self.assertIn(
            response.status_code,
            (200, 404),
            f"{name} refused an API key holding {scopes}: {response.status_code}",
        )

    @parameterized.expand(KEY_ENDPOINTS)
    def test_a_scopeless_key_is_forbidden(self, name, url, scopes):
        response = self.do_api_key_request(url, "GET", self.key_without_scope)

        self.assertEqual(response.status_code, 403, f"{name} let a scopeless key through")

    @parameterized.expand(KEY_ENDPOINTS)
    def test_an_unknown_key_is_unauthorized(self, name, url, scopes):
        response = self.do_api_key_request(url, "GET", "no-such-secret")

        self.assertEqual(response.status_code, 401, f"{name} let an unknown key through")

    @parameterized.expand(READ_ENDPOINTS)
    def test_no_credential_is_unauthorized(self, name, url, scopes):
        # The JWT side of the same guard: `auth` must not have gone missing either.
        response = Client().get(url)

        self.assertEqual(response.status_code, 401, f"{name} is reachable with no credential")

    @parameterized.expand(READ_ENDPOINTS)
    def test_a_scoped_token_is_accepted(self, name, url, scopes):
        self.user_access_token_frodon.scope = " ".join(scopes)
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.do_api_request(url, "GET", self.user_access_token_frodon.token)

        self.assertIn(
            response.status_code,
            (200, 404),
            f"{name} refused a user token holding {scopes}: {response.status_code}",
        )

    def test_a_key_cannot_manage_keys(self):
        """ The scopes of `/api-keys/` are the ones no key may hold.

        `cls.api_key` carries every grantable permission -- `public_scopes()` --
        and still cannot read, create or delete a key. That is `is_public=False`
        on `totem.apikey.*` doing its work, and it is why `ApiKeyController` is
        out of the key sweep above rather than failing it.
        """
        # A valid body on the POST, and the detail URL for the DELETE: ninja
        # validates the body and resolves the route before the permission
        # decorator runs, so a malformed call would answer 422 or 405 and prove
        # nothing about the scopes.
        calls = [
            ("GET", "/api/v1/api-keys/", None),
            ("POST", "/api/v1/api-keys/", json.dumps({"name": "Escalation", "scope": []})),
            ("DELETE", f"/api/v1/api-keys/{self.api_key.pk}/", None),
        ]
        for method, url, data in calls:
            with self.subTest(method=method):
                response = self.do_api_key_request(url, method, self.api_key_secret, data=data)
                self.assertEqual(response.status_code, 403)

        self.assertFalse(ApiKey.objects.filter(name="Escalation").exists())
        self.assertTrue(ApiKey.objects.filter(pk=self.api_key.pk).exists())

    def test_the_sweep_covers_every_controller(self):
        """ No model controller silently escapes the sweep.

        Without this, a resource added with a `permission_map` missing its `read`
        key -- the unscoped-route trap -- would simply drop out of
        `read_endpoints()` and look covered.
        """
        swept = {name for name, dummy_url, dummy_scopes in READ_ENDPOINTS}
        expected = {controller.__name__ for controller in model_controllers()}

        self.assertEqual(expected - swept, set())
        # And every controller is reached by the key sweep or named as forbidden.
        self.assertEqual(
            swept - {name for name, dummy_url, dummy_scopes in KEY_ENDPOINTS},
            KEY_FORBIDDEN,
        )

    def test_every_controller_declares_read_scopes(self):
        # The other half of the same trap: a route whose `permission_map` has no
        # `read` key requires no scope at all.
        for controller in model_controllers():
            with self.subTest(controller=controller.__name__):
                self.assertTrue(
                    getattr(controller, "permission_map", {}).get("read"),
                    f"{controller.__name__} declares no read scopes",
                )
