from datetime import datetime
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.client import MULTIPART_CONTENT
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from base.models import FileReference
from core.testing import APITestCaseMixin
from document.models import Document
from document.services import DocumentService
from document.tests.images import image_bytes, pdf_bytes
from user.access_rights import get_user_scopes

from .common import (
    CONTACT_ELROND_ID,
    DOCUMENT_SCOPES,
    PERMISSION_DENIED,
    TAG_DRAFT_ID,
    TAG_SIGNED_ID,
    CommonTestMixin,
)

# The two text documents of `CommonTestMixin`.
INITIAL_DOCUMENT_COUNT = 2

DOCUMENT_FIELDS = [
    "id",
    "name",
    "document_type",
    "file",
    "thumbnail",
    "text_content",
    "mimetype",
    "checksum",
    "size",
    "date",
    "user",
    "contact",
    "tags",
    "create_date",
    "update_date",
]


# Frozen: the API renders a date to the millisecond, the database keeps microseconds.
@freeze_time("2026-10-15 11:12:13")
class DocumentActionsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `POST /document/documents/upload/`: one `file` document per file part, all
    or nothing. Multipart: the files under `files`, the values every document
    shares (`tags`, `user`, `contact`) as form fields. No `*_access_rules` tests:
    no `BaseRule` is registered for `Document`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = DOCUMENT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/document/documents/upload/"

    # ------------------------------------------
    # Upload
    # ------------------------------------------

    @parameterized.expand(
        [
            ("one file", [("map.pdf", pdf_bytes())], {}, 201, None),
            ("with shared values", [("map.pdf", pdf_bytes())], {"tags": [TAG_DRAFT_ID], "contact": CONTACT_ELROND_ID}, 201, None),
            # The second file is refused: none is created, and `ctx.key` says which.
            (
                "one file refused",
                [("map.pdf", pdf_bytes()), ("logo.svg", b"<svg/>"), ("ring.png", image_bytes())],
                {},
                422,
                (["file", "files"], 1),
            ),
            ("unknown tag", [("map.pdf", pdf_bytes())], {"tags": ["01JT0000000000000000000099"]}, 422, (["form", "tags"], 0)),
            (
                "unknown contact",
                [("map.pdf", pdf_bytes())],
                {"contact": "01JK0000000000000000000099"},
                422,
                (["form", "contact"], 0),
            ),
            ("malformed user", [("map.pdf", pdf_bytes())], {"user": "frodon"}, 422, (["form", "user"], None)),
            # No file part at all: refused by ninja itself.
            ("no file", [], {"tags": [TAG_DRAFT_ID]}, 422, (["file", "files"], None)),
        ]
    )
    def test_upload_request(self, dummy, files, form, status_code, error):
        data = {**form, "files": [SimpleUploadedFile(name, payload) for name, payload in files]}

        response = self.do_request("POST", self.url, data=data, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, status_code)
        if error:
            loc, key = error
            detail = response.json()["detail"]
            self.assertEqual([item["loc"][:2] for item in detail], [loc])
            if key is not None:
                self.assertEqual(detail[0]["ctx"]["key"], key)
            # All or nothing: no row, and no file in the storage.
            self.assertEqual(Document.objects.count(), INITIAL_DOCUMENT_COUNT)
            self.assertFalse(FileReference.objects.exists())

    def test_upload_request_too_many_files(self):
        with patch.object(DocumentService, "MAX_UPLOAD_COUNT", 2):
            response = self.do_request(
                "POST",
                self.url,
                data={"files": [SimpleUploadedFile(f"map{index}.pdf", pdf_bytes()) for index in range(3)]},
                content_type=MULTIPART_CONTENT,
            )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual([item["loc"] for item in detail], [["file", "files"]])
        self.assertEqual(detail[0]["ctx"]["key"], "files")
        self.assertEqual(Document.objects.count(), INITIAL_DOCUMENT_COUNT)

    def test_upload_response(self):
        response = self.do_request(
            "POST",
            self.url,
            data={
                "files": [SimpleUploadedFile("map.pdf", pdf_bytes()), SimpleUploadedFile("ring.png", image_bytes())],
                "tags": [TAG_DRAFT_ID, TAG_SIGNED_ID],
                "user": str(self.user_frodon.pk),
                "contact": CONTACT_ELROND_ID,
            },
            content_type=MULTIPART_CONTENT,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)
        # In the order of the files, each named after its file, with a thumbnail.
        self.assertEqual([item["name"] for item in data], ["map.pdf", "ring.png"])
        for item in data:
            document = Document.objects.get(pk=item["id"])
            self.assert_api_format(item, document)
            self.assertEqual(document.document_type, "file")
            self.assertEqual(str(document.user_id), str(self.user_frodon.pk))
            self.assertEqual(document.contact_id, CONTACT_ELROND_ID)
            self.assertEqual(set(document.tags.values_list("id", flat=True)), {TAG_DRAFT_ID, TAG_SIGNED_ID})
            self.assertIsNotNone(item["thumbnail"])

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.create"], 201),
            (["totem.document.read", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.create"], 403),
        ]
    )
    def test_upload_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request(
            "POST", self.url, data={"files": [SimpleUploadedFile("map.pdf", pdf_bytes())]},
            content_type=MULTIPART_CONTENT,
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.create"], 201),
            (["totem.document.read", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.create"], 403),
        ]
    )
    def test_upload_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request(
            "POST", self.url, auth="apikey", data={"files": [SimpleUploadedFile("map.pdf", pdf_bytes())]},
            content_type=MULTIPART_CONTENT,
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None, content_type=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would. `content_type=MULTIPART_CONTENT`
        makes the test client encode `data` as multipart instead of JSON.
        """
        extra = {"content_type": content_type} if content_type else {}
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {}, **extra)
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {}, **extra)

    def assert_api_format(self, api_data, obj):
        """ The same document as the CRUD routes render, see `DocumentAPITest`. """
        for name in ("id", "name", "document_type", "text_content", "mimetype", "checksum", "size"):
            self.assertEqual(api_data[name], getattr(obj, name))
        for name in ("file", "thumbnail"):
            stored = getattr(obj, name)
            if stored:
                # Signed: the signature and its expiry vary, the path does not.
                self.assertEqual(api_data[name].split("?")[0], stored.storage.url(stored.name).split("?")[0])
            else:
                self.assertIsNone(api_data[name])
        self.assertEqual(api_data["date"], obj.date.isoformat() if obj.date else None)
        for name in ("create_date", "update_date"):
            self.assertEqual(datetime.fromisoformat(api_data[name]), getattr(obj, name))
        self.assertEqual(api_data["user"], {"id": str(obj.user.pk), "login": obj.user.username} if obj.user else None)
        self.assertEqual(
            api_data["contact"],
            {"id": obj.contact.pk, "display_name": obj.contact.display_name, "is_company": obj.contact.is_company}
            if obj.contact else None,
        )
        self.assertEqual(
            sorted(api_data["tags"], key=lambda tag: tag["id"]),
            [
                {
                    "id": tag.pk,
                    "name": tag.name,
                    "category": {"id": tag.category.pk, "name": tag.category.name, "color": tag.category.color},
                }
                for tag in obj.tags.order_by("pk")
            ],
        )

        self.assertEqual(set(DOCUMENT_FIELDS), set(api_data))
