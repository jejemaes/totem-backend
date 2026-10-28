import json
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time
from parameterized import parameterized

from authentication.models import ApiKey
from authentication.testing import public_scopes
from authentication.tokens import hash_secret
from core.testing import APITestCaseMixin
from user.models import User, UserRole
from user.tests.test_api.common import CommonTestMixin

KEY_FIELDS = ["id", "name", "scope", "is_active", "expires_at", "created_at"]
CREATED_FIELDS = KEY_FIELDS + ["secret"]


@freeze_time("2024-11-18 11:12:13")
class ApiKeyAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = "/api/v1/api-keys/"

        cls.reporting = ApiKey.objects.create(
            name="Reporting",
            secret_hash=hash_secret("reporting-secret"),
            scope=["totem.user.read"],
        )
        cls.url_detail = f"{cls.url}{cls.reporting.pk}/"

        cls.payload_create = {"name": "Nightly Export", "scope": ["totem.contact.read"]}

    @property
    def token(self):
        return self.user_access_token_frodon.token

    def with_scope(self, *scopes):
        self.user_access_token_frodon.scope = " ".join(scopes)
        self.user_access_token_frodon.save(update_fields=["scope"])
        return self.user_access_token_frodon.token

    # ------------------------------------------
    # Tests List
    # ------------------------------------------

    def test_list(self):
        response = self.do_api_request(self.url, "GET", self.with_scope("totem.apikey.read"))

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        # `cls.api_key` of the fixture, plus the one above.
        self.assertEqual(len(results), 2)
        self._assert_api_format(
            next(item for item in results if item["id"] == str(self.reporting.pk)),
            self.reporting,
            KEY_FIELDS,
        )

    def test_list_filter_is_active(self):
        ApiKey.objects.create(
            name="Retired", secret_hash=hash_secret("retired"), scope=[], is_active=False
        )

        response = self.do_api_request(
            self.url, "GET", self.with_scope("totem.apikey.read"), params={"is_active": "false"}
        )

        self.assertEqual([item["name"] for item in response.json()["results"]], ["Retired"])

    @parameterized.expand(
        [
            ("totem.apikey.read", 200),
            ("totem.apikey.create", 403),
            ("totem.apikey.delete", 403),
            ("totem.user.read", 403),
        ]
    )
    def test_list_access_rights(self, scope, status_code):
        response = self.do_api_request(self.url, "GET", self.with_scope(scope))
        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Tests Retrieve
    # ------------------------------------------

    def test_retrieve(self):
        response = self.do_api_request(
            self.url_detail, "GET", self.with_scope("totem.apikey.read")
        )

        self.assertEqual(response.status_code, 200)
        self._assert_api_format(response.json(), self.reporting, KEY_FIELDS)

    @parameterized.expand(
        [
            ("totem.apikey.read", 200),
            ("totem.apikey.create", 403),
            ("totem.apikey.delete", 403),
        ]
    )
    def test_retrieve_access_rights(self, scope, status_code):
        response = self.do_api_request(self.url_detail, "GET", self.with_scope(scope))
        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create(self):
        response = self.do_api_request(
            self.url,
            "POST",
            self.with_scope("totem.apikey.create"),
            data=json.dumps(self.payload_create),
        )

        self.assertEqual(response.status_code, 201)
        body = response.json()
        created = ApiKey.objects.get(name="Nightly Export")
        self._assert_api_format(body, created, CREATED_FIELDS)
        # The one response of the API that carries a usable credential.
        self.assertEqual(created.secret_hash, hash_secret(body["secret"]))

    def test_the_returned_secret_authenticates(self):
        secret = self.do_api_request(
            self.url,
            "POST",
            self.with_scope("totem.apikey.create"),
            data=json.dumps(self.payload_create),
        ).json()["secret"]

        response = self.do_api_key_request("/api/v1/contacts/", "GET", secret)

        self.assertEqual(response.status_code, 200)

    def test_create_with_no_scope(self):
        response = self.do_api_request(
            self.url,
            "POST",
            self.with_scope("totem.apikey.create"),
            data=json.dumps({"name": "Useless", "scope": []}),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["scope"], [])

    def test_omitting_scope_creates_a_powerless_key(self):
        """ The guarantee is the *value* of the default, not that it be typed.

        The schema mirrors the model (`blank=True, default=list`), so `scope` may
        be left out -- and what it defaults to is an empty list. What must never
        happen is a key inheriting the scopes of whoever created it, and that is
        what this pins: the creator below holds `totem.apikey.create`, and the key
        comes out holding nothing.
        """
        response = self.do_api_request(
            self.url,
            "POST",
            self.with_scope("totem.apikey.create"),
            data=json.dumps({"name": "Implicit"}),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["scope"], [])
        self.assertEqual(ApiKey.objects.get(name="Implicit").scopes, set())

    def test_create_with_a_scope_no_key_may_hold(self):
        # `totem.apikey.*` is `is_public=False`, so it is not among the choices of
        # `ApiKey.scope` and the generated enum refuses it outright: a key able to
        # mint keys cannot be created at all.
        response = self.do_api_request(
            self.url,
            "POST",
            self.with_scope("totem.apikey.create"),
            data=json.dumps({"name": "Escalation", "scope": ["totem.apikey.create"]}),
        )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(ApiKey.objects.filter(name="Escalation").exists())

    def test_create_with_an_unregistered_scope(self):
        response = self.do_api_request(
            self.url,
            "POST",
            self.with_scope("totem.apikey.create"),
            data=json.dumps({"name": "Bogus", "scope": ["totem.nothing.read"]}),
        )

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("totem.apikey.create", 201),
            ("totem.apikey.read", 403),
            ("totem.apikey.delete", 403),
        ]
    )
    def test_create_access_rights(self, scope, status_code):
        response = self.do_api_request(
            self.url, "POST", self.with_scope(scope), data=json.dumps(self.payload_create)
        )
        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_a_key_cannot_be_updated(self):
        """ No PATCH route at all: `ApiKeyService` composes no `UpdateMixin` and
        the controller inherits no update mixin. Widening the scopes of a key in
        circulation would be a silent privilege escalation. """
        response = self.do_api_request(
            self.url_detail,
            "PATCH",
            self.with_scope(*public_scopes(), "totem.apikey.read", "totem.apikey.create"),
            data=json.dumps({"scope": ["totem.user.delete"]}),
        )

        self.assertEqual(response.status_code, 405)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete(self):
        response = self.do_api_request(
            self.url_detail, "DELETE", self.with_scope("totem.apikey.delete")
        )

        self.assertEqual(response.status_code, 204)
        self.assertFalse(ApiKey.objects.filter(pk=self.reporting.pk).exists())

    @parameterized.expand(
        [
            ("totem.apikey.delete", 204),
            ("totem.apikey.read", 403),
            ("totem.apikey.create", 403),
        ]
    )
    def test_delete_access_rights(self, scope, status_code):
        response = self.do_api_request(self.url_detail, "DELETE", self.with_scope(scope))
        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Authenticating *with* a key
    # ------------------------------------------

    def test_a_key_reaches_a_route_its_scopes_cover(self):
        response = self.do_api_key_request("/api/v1/user-roles/", "GET", self.api_key_secret)

        self.assertEqual(response.status_code, 200)

    def test_a_key_without_scope_reaches_nothing(self):
        key = ApiKey.objects.create(
            name="Useless", secret_hash=hash_secret("useless-secret"), scope=[]
        )

        for url in ("/api/v1/user-roles/", "/api/v1/contacts/", self.url):
            with self.subTest(url=url):
                response = self.do_api_key_request(url, "GET", "useless-secret")
                self.assertEqual(response.status_code, 403)

    def test_a_key_is_nobody(self):
        """ `/users/me/` has no answer for a machine caller: 403, not a crash.

        `IsAuthenticated` guards on `auth.user`, which an `ApiKey` leaves at
        `None`. Before the guard, `Request._get_request_user` fell back to the
        `AnonymousUser` of the middleware and `AccessContext` raised on it.
        """
        response = self.do_api_key_request("/api/v1/users/me/", "GET", self.api_key_secret)

        self.assertEqual(response.status_code, 403)

    def test_a_key_is_subject_to_no_row_rule(self):
        """ ⚠️ A documented property, not an oversight -- and not what one guesses.

        Row-level rules are assembled from the acting user's roles. A key has no
        user, so `get_access_roles()` returns `[]`, `apply_access_rules` builds no
        lookup, and the queryset comes back unfiltered. The contrast below is the
        whole point: the same scope, restricted for a user, unrestricted for a key.

        Bounding a key would take an ownership column and a `BaseRule`, not a
        setting -- which is why this is pinned on the row *count*, not on the 200.
        """
        UserRole.objects.filter(pk=self.role.pk).update(
            permissions=["totem.user.read"], rules=["user_manage_own_profile"]
        )

        as_user = self.do_api_request(
            "/api/v1/users/", "GET", self.with_scope("totem.user.read")
        )
        self.assertEqual(as_user.status_code, 200)
        self.assertEqual(
            [item["id"] for item in as_user.json()["results"]], [str(self.user_frodon.pk)]
        )

        as_key = self.do_api_key_request("/api/v1/users/", "GET", self.api_key_secret)
        self.assertEqual(as_key.status_code, 200)
        self.assertEqual(len(as_key.json()["results"]), User.objects.count())

    @parameterized.expand(
        [
            ("unknown", "no-such-secret"),
            ("inactive", "inactive-secret"),
            ("expired", "expired-secret"),
            ("empty", ""),
        ]
    )
    def test_an_unusable_key_is_a_401(self, label, secret):
        ApiKey.objects.create(
            name="Inactive", secret_hash=hash_secret("inactive-secret"), scope=public_scopes(),
            is_active=False,
        )
        ApiKey.objects.create(
            name="Expired", secret_hash=hash_secret("expired-secret"), scope=public_scopes(),
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        response = self.do_api_key_request("/api/v1/user-roles/", "GET", secret)

        self.assertEqual(response.status_code, 401)

    def test_the_header_is_case_insensitive(self):
        # Django's `HttpHeaders` normalises it, so any casing a client sends works.
        response = self.do_api_key_request("/api/v1/user-roles/", "GET", self.api_key_secret)
        self.assertEqual(response.status_code, 200)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def _assert_api_format(self, api_data, obj, fields):
        if not fields:
            fields = KEY_FIELDS
        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "scope" in fields:
            self.assertEqual(api_data["scope"], obj.scope)
        if "is_active" in fields:
            self.assertEqual(api_data["is_active"], obj.is_active)
        if "expires_at" in fields:
            if obj.expires_at is None:
                self.assertIsNone(api_data["expires_at"])
            else:
                self.assertEqual(api_data["expires_at"], _isoformat(obj.expires_at))
        if "created_at" in fields:
            self.assertEqual(api_data["created_at"], _isoformat(obj.created_at))
        if "secret" in fields:
            # Never readable from the row: only the response of a creation has it.
            self.assertEqual(hash_secret(api_data["secret"]), obj.secret_hash)

        # The shape of the response is the contract. In particular, `secret_hash`
        # must never appear in any of them.
        self.assertEqual(set(fields), set(api_data.keys()))
        self.assertNotIn("secret_hash", api_data)


def _isoformat(value):
    """ A datetime as the API renders it: UTC written `Z`, not `+00:00`. """
    return value.isoformat().replace("+00:00", "Z")
