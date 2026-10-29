from django.test import TestCase
from parameterized import parameterized

from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Media

from .common import MEDIA_SCOPES, PERMISSION_DENIED, CommonTestMixin

MEDIA_ID1 = "01M209K5BNS12QRPHXFWVJNVX1"
MEDIA_ID2 = "01M209K5BNS12QRPHXFWVJNVX2"
MEDIA_ID3 = "01M209K5BNS12QRPHXFWVJNVX3"
MEDIA_ID4 = "01ARZ3NDEKTSV4RRFFQ69G5FAV"  # matches no media


class MediaDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `Media`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # A checksum given: no file to read, nothing written to storage.
        Media.objects.bulk_create([
            Media(id=MEDIA_ID1, name="map-of-the-shire.png", content="website/map-of-the-shire.png", checksum="a" * 40),
            Media(
                id=MEDIA_ID2, name="red-book-of-westmarch.pdf", content="website/red-book-of-westmarch.pdf",
                checksum="b" * 40,
            ),
            Media(id=MEDIA_ID3, name="moria-gate.png", content="website/moria-gate.png", checksum="c" * 40),
        ])

        cls.role.permissions = MEDIA_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/medias/display-name/"
        cls.ids = f"{MEDIA_ID2},{MEDIA_ID1},{MEDIA_ID3}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            (f"{MEDIA_ID2},{MEDIA_ID1}", 200, [MEDIA_ID2, MEDIA_ID1]),
            (f"{MEDIA_ID1},{MEDIA_ID2}", 200, [MEDIA_ID1, MEDIA_ID2]),
            # Blanks around the ids and empty items are dropped.
            (f" {MEDIA_ID3} ,,", 200, [MEDIA_ID3]),
            # An unknown id is absent, not an error.
            (f"{MEDIA_ID1},{MEDIA_ID4}", 200, [MEDIA_ID1]),
            ("", 200, []),
            # A malformed id is the client's mistake.
            (f"{MEDIA_ID1},palantir", 422, None),
        ]
    )
    def test_display_name_request(self, ids, status_code, expected_pks):
        response = self.do_request("GET", self.url, params={"id": ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual([item["id"] for item in response.json()], expected_pks)
        else:
            self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])

    def test_display_name_response(self):
        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 3)
        for item in response.json():
            self.assert_api_format(item, Media.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.read"], 200),
            (["totem.websitemedia.create", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.read"], 403),
        ]
    )
    def test_display_name_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.read"], 200),
            (["totem.websitemedia.create", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.read"], 403),
        ]
    )
    def test_display_name_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey", params={"id": self.ids})

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

    def assert_api_format(self, api_data, obj):
        self.assertEqual(api_data, {"id": str(obj.pk), "name": obj.name})
