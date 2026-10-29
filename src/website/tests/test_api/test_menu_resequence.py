import json

from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Menu

from .common import (
    MENU_ID1,
    MENU_ID2,
    MENU_ID3,
    MENU_ID4,
    MENU_ID5,
    MENU_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

UNKNOWN_MENU_ID = "01JZ0000000000000000000099"

# The sequences of `CommonTestMixin`.
SEQUENCES = {MENU_ID1: 20, MENU_ID2: 10, MENU_ID3: 25, MENU_ID4: 10, MENU_ID5: 45}


class MenuResequenceAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `POST /website/menus/resequence/`, which answers with no body: hence no
    `assert_api_format` here.

    No `*_access_rules` tests: no `BaseRule` is registered for `Menu`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = MENU_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/menus/resequence/"
        cls.payload = {"ids": [MENU_ID5, MENU_ID4]}

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            ("complete list", {"ids": [MENU_ID5, MENU_ID4]}, 201, None),
            ("partial list", {"ids": [MENU_ID5]}, 201, None),
            ("empty list", {"ids": []}, 201, None),
            ("offset 0", {"ids": [MENU_ID5], "offset": 0}, 201, None),
            ("offset", {"ids": [MENU_ID5], "offset": 20}, 201, None),
            ("unknown pk", {"ids": [MENU_ID5, UNKNOWN_MENU_ID]}, 422, "ids"),
            ("not a ulid", {"ids": [MENU_ID5, "not-a-ulid"]}, 422, "ids"),
            ("repeated pk", {"ids": [MENU_ID5, MENU_ID5]}, 422, "ids"),
            ("no ids", {"offset": 0}, 422, "ids"),
            ("negative offset", {"ids": [MENU_ID5], "offset": -1}, 422, "offset"),
            ("offset not an integer", {"ids": [MENU_ID5], "offset": "first"}, 422, "offset"),
            # An object: neither a bare list nor anything else.
            ("a bare list", [MENU_ID5], 422, None),
            # A JSON string, encoded here: a bare `str` body is sent as is, and
            # would answer 400 for not being JSON at all.
            ("a string", json.dumps(MENU_ID5), 422, None),
        ]
    )
    def test_resequence_request(self, dummy, payload, status_code, field):
        response = self.do_request("POST", self.url, data=payload)

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            if field:
                self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", field])
            # Nothing is renumbered.
            self.assertEqual(dict(Menu.objects.values_list("pk", "sequence")), SEQUENCES)

    @parameterized.expand(
        [
            # Across levels: the sequence orders siblings, numbering is the client's call.
            ("siblings", {"ids": [MENU_ID5, MENU_ID4]}, {MENU_ID5: 1, MENU_ID4: 2}),
            ("partial", {"ids": [MENU_ID3]}, {MENU_ID3: 1}),
            # A page of a list: numbered where it sits in the whole list.
            ("page of a list", {"ids": [MENU_ID5, MENU_ID4], "offset": 20}, {MENU_ID5: 21, MENU_ID4: 22}),
        ]
    )
    def test_resequence_response(self, dummy, payload, expected):
        response = self.do_request("POST", self.url, data=payload)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content, b"")
        # The others are untouched.
        self.assertEqual(dict(Menu.objects.values_list("pk", "sequence")), {**SEQUENCES, **expected})

    @parameterized.expand(
        [
            ([], 403),
            # Numbering menu items is updating them.
            (["totem.websitemenu.update"], 201),
            (["totem.websitemenu.create", "totem.websitemenu.read", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.update"], 403),
        ]
    )
    def test_resequence_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)
            self.assertEqual(dict(Menu.objects.values_list("pk", "sequence")), SEQUENCES)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemenu.update"], 201),
            (["totem.websitemenu.create", "totem.websitemenu.read", "totem.websitemenu.delete"], 403),
            (["totem.websitepage.update"], 403),
        ]
    )
    def test_resequence_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})
