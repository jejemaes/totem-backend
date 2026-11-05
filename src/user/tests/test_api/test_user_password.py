from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from user.models import User

from .common import USER_ID1, USER_ID2, CommonTestMixin

USER_ID5 = "5263de93-e694-11ef-b873-34610551afcd"  # matches no user

OLD_PASSWORD = "Pr3cious-Ring"
NEW_PASSWORD = "Mount-D00m-Lava"

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class UserPasswordAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        for user in (cls.user_frodon, cls.user_gollum):
            user.set_password(OLD_PASSWORD)
            user.save()

        # Frodon acts through the role every user of `CommonTestMixin` holds. It is
        # granted the password of others and no rule here; the access tests narrow it.
        cls.role.permissions = ["totem.user.password"]
        cls.role.rules = []
        cls.role.save()

        cls.url_me = "/api/v1/users/me/password/"
        cls.url_detail = f"/api/v1/users/{USER_ID2}/password/"
        cls.payload_change = {"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD}
        cls.payload_set = {"new_password": NEW_PASSWORD}

    # ------------------------------------------
    # Change My Password (/users/me/password/)
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"new_password": NEW_PASSWORD}, 422, "old_password"),
            ({"old_password": OLD_PASSWORD}, 422, "new_password"),
            ({"old_password": 1234, "new_password": NEW_PASSWORD}, 422, "old_password"),
            ({"old_password": OLD_PASSWORD, "new_password": None}, 422, "new_password"),
            ({"old_password": "not-my-password", "new_password": NEW_PASSWORD}, 422, "old_password"),
            # `AUTH_PASSWORD_VALIDATORS`, one per validator
            ({"old_password": OLD_PASSWORD, "new_password": "Sh0rt"}, 422, "new_password"),
            ({"old_password": OLD_PASSWORD, "new_password": "password123"}, 422, "new_password"),
            ({"old_password": OLD_PASSWORD, "new_password": "84629173650"}, 422, "new_password"),
            ({"old_password": OLD_PASSWORD, "new_password": "frodon@lacomte.com"}, 422, "new_password"),
            ({"old_password": OLD_PASSWORD, "new_password": NEW_PASSWORD}, 204, None),
        ]
    )
    def test_password_request(self, body, status_code, error_field):
        response = self.do_request("POST", self.url_me, data=body)

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(error_field, [error["loc"][-1] for error in response.json()["detail"]])
        # Nothing is written unless all of it is valid.
        self.assertEqual(
            User.objects.get(pk=USER_ID1).check_password(OLD_PASSWORD),
            status_code != 204,
        )

    def test_password_response(self):
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))

        response = self.do_api_request(self.url_me, "POST", token, data=self.payload_change)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertTrue(User.objects.get(pk=USER_ID1).check_password(NEW_PASSWORD))
        # No session is revoked: the token the change was made with still works.
        response = self.do_api_request("/api/v1/users/me/", "GET", token)
        self.assertEqual(response.status_code, 200)

    @parameterized.expand(
        [
            # Any user may change their own password, whatever their scopes.
            ("user", [], 204),
            ("user", ["totem.user.update"], 204),
            ("user", ["totem.user.password"], 204),
            # A key has no password of its own.
            ("apikey", None, 403),
            ("anonymous", None, 401),
        ]
    )
    def test_password_access_rights(self, auth, permissions, status_code):
        if permissions is not None:
            self.role.permissions = permissions
            self.role.save()

        response = self.do_request("POST", self.url_me, auth=auth, data=self.payload_change)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)
        self.assertEqual(
            User.objects.get(pk=USER_ID1).check_password(NEW_PASSWORD),
            status_code == 204,
        )

    @parameterized.expand(
        [
            ([],),
            (["user_manage_own_profile"],),
            (["user_manage_all_user"],),
        ]
    )
    def test_password_access_rules(self, rules):
        # The rules do not narrow one's own password, and whatever they allow on
        # others, only the acting user's password is written.
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", self.url_me, data=self.payload_change)

        self.assertEqual(response.status_code, 204)
        self.assertTrue(User.objects.get(pk=USER_ID1).check_password(NEW_PASSWORD))
        self.assertTrue(User.objects.get(pk=USER_ID2).check_password(OLD_PASSWORD))

    # ------------------------------------------
    # Set the Password of a User (/users/{id}/password/)
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 422, "new_password"),
            ({"new_password": 1234}, 422, "new_password"),
            ({"new_password": None}, 422, "new_password"),
            ({"new_password": "Sh0rt"}, 422, "new_password"),
            ({"new_password": "password123"}, 422, "new_password"),
            ({"new_password": "84629173650"}, 422, "new_password"),
            # Compared to the target user, not to the acting one.
            ({"new_password": "gollum@precious.com"}, 422, "new_password"),
            # No current password is asked: the administrator does not know it.
            ({"new_password": NEW_PASSWORD}, 204, None),
        ]
    )
    def test_password_admin_request(self, body, status_code, error_field):
        response = self.do_request("POST", self.url_detail, data=body)

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(error_field, [error["loc"][-1] for error in response.json()["detail"]])
        self.assertEqual(
            User.objects.get(pk=USER_ID2).check_password(OLD_PASSWORD),
            status_code != 204,
        )

    @parameterized.expand(
        [
            (USER_ID2, 204),
            (USER_ID5, 404),
        ]
    )
    def test_password_admin_response(self, pk, status_code):
        response = self.do_request("POST", f"/api/v1/users/{pk}/password/", data=self.payload_set)

        self.assertEqual(response.status_code, status_code)
        if status_code == 204:
            self.assertEqual(response.content, b"")
            self.assertTrue(User.objects.get(pk=pk).check_password(NEW_PASSWORD))

    @parameterized.expand(
        [
            ("user", [], USER_ID2, 403),
            ("user", ["totem.user.password"], USER_ID2, 204),
            ("user", ["totem.user.create", "totem.user.read", "totem.user.update", "totem.user.delete"], USER_ID2, 403),
            # `totem.user.update` reaches one's own profile, never one's password
            # without the current one: that is what `/me/password/` is for.
            ("user", ["totem.user.update"], USER_ID1, 403),
            # The key holds every public scope, and this one is not public.
            ("apikey", None, USER_ID2, 403),
            ("anonymous", None, USER_ID2, 401),
        ]
    )
    def test_password_admin_access_rights(self, auth, permissions, pk, status_code):
        if permissions is not None:
            self.role.permissions = permissions
            self.role.save()

        response = self.do_request("POST", f"/api/v1/users/{pk}/password/", auth=auth, data=self.payload_set)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)
        self.assertEqual(
            User.objects.get(pk=pk).check_password(NEW_PASSWORD),
            status_code == 204,
        )

    @parameterized.expand(
        [
            ([], USER_ID2, 204),
            (["user_manage_own_profile"], USER_ID1, 204),
            (["user_manage_own_profile"], USER_ID2, 404),
            (["user_manage_all_user"], USER_ID2, 204),
        ]
    )
    def test_password_admin_access_rules(self, rules, pk, status_code):
        self.role.rules = rules
        self.role.save()

        response = self.do_request("POST", f"/api/v1/users/{pk}/password/", data=self.payload_set)

        self.assertEqual(response.status_code, status_code)
        # Only the record in reach was written.
        self.assertEqual(
            User.objects.get(pk=pk).check_password(NEW_PASSWORD),
            status_code == 204,
        )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None):
        """ Call the API as Frodon (`auth="user"`), as the API key (`"apikey"`), or
        with no credential at all (`"anonymous"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data)
        if auth == "anonymous":
            return self._do_request(url, method, data=data)
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data)
