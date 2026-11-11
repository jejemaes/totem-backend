import json

from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from document.models import DocumentTag
from user.access_rights import get_user_scopes

from .common import (
    TAG_DRAFT_ID,
    TAG_SCOPES,
    TAG_SHIRE_ID,
    TAG_SIGNED_ID,
    PERMISSION_DENIED,
    CommonTestMixin,
)

UNKNOWN_ID = "01JT0000000000000000000099"  # matches no record

# The sequences of `CommonTestMixin`.
INITIAL_SEQUENCES = {TAG_DRAFT_ID: 1, TAG_SIGNED_ID: 2, TAG_SHIRE_ID: 10}


class DocumentTagResequenceAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `POST /document/tags/resequence/`. No `*_access_rules` tests: no
    `BaseRule` is registered for `DocumentTag`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = TAG_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/document/tags/resequence/"
        cls.payload = {"ids": [TAG_SIGNED_ID, TAG_DRAFT_ID]}

    # ------------------------------------------
    # Resequence
    # ------------------------------------------

    @parameterized.expand(
        [
            ("reversed", {"ids": [TAG_SIGNED_ID, TAG_DRAFT_ID]}, 201, None, {TAG_SIGNED_ID: 1, TAG_DRAFT_ID: 2}),
            # Only the records given are numbered.
            ("partial", {"ids": [TAG_SIGNED_ID]}, 201, None, {TAG_SIGNED_ID: 1}),
            ("empty", {"ids": []}, 201, None, {}),
            # A page of a list: numbered where it sits in the whole list.
            ("page of a list", {"ids": [TAG_SIGNED_ID, TAG_DRAFT_ID], "offset": 20}, 201, None, {TAG_SIGNED_ID: 21, TAG_DRAFT_ID: 22}),
            ("unknown pk", {"ids": [TAG_SIGNED_ID, UNKNOWN_ID]}, 422, "ids", {}),
            ("not a ulid", {"ids": [TAG_SIGNED_ID, "not-a-ulid"]}, 422, "ids", {}),
            ("repeated pk", {"ids": [TAG_SIGNED_ID, TAG_SIGNED_ID]}, 422, "ids", {}),
            ("no ids", {"offset": 0}, 422, "ids", {}),
            ("negative offset", {"ids": [TAG_SIGNED_ID], "offset": -1}, 422, "offset", {}),
            ("a bare list", [TAG_SIGNED_ID, TAG_DRAFT_ID], 422, None, {}),
        ]
    )
    def test_resequence_request(self, dummy, payload, status_code, error_field, changed):
        response = self.do_request("POST", self.url, data=json.dumps(payload))

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual(response.json()["detail"][0]["loc"][:3], ["body", "request_body", error_field])
        # Nothing is written on an error.
        self.assertEqual(dict(DocumentTag.objects.values_list("id", "sequence")), {**INITIAL_SEQUENCES, **changed})

    def test_resequence_response(self):
        response = self.do_request("POST", self.url, data=json.dumps(self.payload))

        self.assertEqual(response.status_code, 201)
        # No body, hence no `assert_api_format` in this class.
        self.assertEqual(response.content, b"")

    @parameterized.expand(
        [
            ([], 403),
            # Numbering the records is updating them.
            (["totem.documenttag.update"], 201),
            (["totem.documenttag.create", "totem.documenttag.read", "totem.documenttag.delete"], 403),
            (["totem.documenttagcategory.update"], 403),
        ]
    )
    def test_resequence_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=json.dumps(self.payload))

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.documenttag.update"], 201),
            (["totem.documenttag.create", "totem.documenttag.read", "totem.documenttag.delete"], 403),
            (["totem.documenttagcategory.update"], 403),
        ]
    )
    def test_resequence_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=json.dumps(self.payload))

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
