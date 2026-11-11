from datetime import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.client import MULTIPART_CONTENT
from freezegun import freeze_time
from parameterized import parameterized

from authentication.testing import mint_access_token
from base.models import FileReference
from core.testing import APITestCaseMixin
from document.models import Document
from document.tests.images import image_bytes, pdf_bytes
from user.access_rights import get_user_scopes
from user.models import User
from user.tests.test_api.common import USER_ID1

from .common import (
    CATEGORY_REALM_ID,
    CATEGORY_STATUS_ID,
    CONTACT_ELROND_ID,
    CONTACT_GALADRIEL_ID,
    DOCUMENT_MINUTES_ID,
    DOCUMENT_NOTES_ID,
    DOCUMENT_SCOPES,
    PERMISSION_DENIED,
    TAG_DRAFT_ID,
    TAG_SHIRE_ID,
    TAG_SIGNED_ID,
    CommonTestMixin,
)

DOCUMENT_ID4 = "01JX0000000000000000000099"  # matches no document

ALL_DOCUMENT_IDS = [DOCUMENT_NOTES_ID, DOCUMENT_MINUTES_ID]

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

# The fields of the creation having a default: the nullable ones. `name` and
# `document_type` have none, nor does `tags`, a many-to-many.
DOCUMENT_DEFAULT_FIELDS = ["file", "text_content", "date", "user", "contact"]

# As Frodon, on the frozen day: the acting user, and today.
DOCUMENT_DEFAULT_VALUES = {
    **{name: None for name in DOCUMENT_DEFAULT_FIELDS},
    "date": "2026-10-15",
    "user": USER_ID1,
}


# Frozen: the API renders a date to the millisecond, the database keeps microseconds.
@freeze_time("2026-10-15 11:12:13")
class DocumentAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `Document`, so
    whoever holds a scope reaches every document.

    The creation is `multipart/form-data`, a text as well as a file: see
    `DocumentController`. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = DOCUMENT_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/document/documents/"
        cls.url_detail = f"/api/v1/document/documents/{DOCUMENT_NOTES_ID}/"
        cls.url_default_values = "/api/v1/document/documents/default-values/"
        cls.payload_create = {
            "name": "Letter to Bilbo",
            "document_type": "text",
            "text_content": "<p>Dear Bilbo</p>",
            "date": "2026-03-25",
            "user": str(cls.user_frodon.pk),
            "contact": CONTACT_GALADRIEL_ID,
            "tags": [TAG_DRAFT_ID, TAG_SHIRE_ID],
        }
        cls.payload_update = {
            "name": "Notes of the Council",
            "text_content": "<p>One ring to rule them all</p>",
            "date": "3018-10-25",
            "contact": CONTACT_GALADRIEL_ID,
            "tags": [TAG_SIGNED_ID],
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_DOCUMENT_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_DOCUMENT_IDS))

        for item in data["results"]:
            self.assert_api_format(item, Document.objects.get(id=item["id"]))

    def test_list_response_file(self):
        # A list serializes the stored path, which the schema turns into the
        # signed URL a retrieve gives: the same value on both routes.
        created = self.do_request(
            "POST", self.url, data={"document_type": "file", "file": SimpleUploadedFile("ring.png", image_bytes())},
            content_type=MULTIPART_CONTENT,
        ).json()

        rows = {item["id"]: item for item in self.do_request("GET", self.url).json()["results"]}

        self.assert_api_format(rows[created["id"]], Document.objects.get(pk=created["id"]))
        self.assertTrue(rows[created["id"]]["file"].startswith("/media/private/document/"))
        self.assertTrue(rows[created["id"]]["thumbnail"].startswith("/media/private/document/thumbnails/"))

    @parameterized.expand(
        [
            ({"tag": TAG_DRAFT_ID}, [DOCUMENT_NOTES_ID]),
            # Once each, though the notes carry two of them.
            ({"tag": f"{TAG_DRAFT_ID},{TAG_SHIRE_ID},{TAG_SIGNED_ID}"}, ALL_DOCUMENT_IDS),
            ({"tag_category": CATEGORY_REALM_ID}, [DOCUMENT_NOTES_ID]),
            ({"tag_category": f"{CATEGORY_STATUS_ID},{CATEGORY_REALM_ID}"}, ALL_DOCUMENT_IDS),
            ({"contact": CONTACT_ELROND_ID}, [DOCUMENT_NOTES_ID]),
            ({"contact": "null"}, [DOCUMENT_MINUTES_ID]),
            ({"contact": f"{CONTACT_GALADRIEL_ID},null"}, [DOCUMENT_MINUTES_ID]),
            ({"document_type": "text"}, ALL_DOCUMENT_IDS),
            ({"document_type": "file"}, []),
            ({"mimetype": "text/"}, ALL_DOCUMENT_IDS),
            ({"mimetype": "image/"}, []),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ({"tag": "not-a-ulid"}, "tag"),
            # A document does not carry a null tag.
            ({"tag": "null"}, "tag"),
            ({"tag_category": "not-a-ulid"}, "tag_category"),
            ({"contact": "not-a-ulid"}, "contact"),
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        # The last name in `loc`: a multi-valued filter puts the index of the faulty item after it.
        self.assertEqual([[part for part in detail["loc"] if isinstance(part, str)][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["-create_date", "id"]),  # default: the newest first
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["size"], ["size", "id"]),
            (["-size"], ["-size", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in Document.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            # Every relation costs its prefetch, the tags two: theirs, and their categories'.
            ([], DOCUMENT_FIELDS, 9),  # default means all fields
            (["name"], ["id", "name"], 5),  # `id` is always returned
            (["tags"], ["id", "tags"], 7),
            (["contact"], ["id", "contact"], 6),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_DOCUMENT_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Document.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "tags"],),
            (["contact_id"],),  # the ORM column, not the field
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("ELROND", [DOCUMENT_NOTES_ID]),  # case insensitive
            ("fellowship", [DOCUMENT_MINUTES_ID]),
            ("of the", ALL_DOCUMENT_IDS),
            ("mordor", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

    def test_list_without_credentials(self):
        response = Client().get(self.url)

        self.assertEqual(response.status_code, 401)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.read"], 200),
            (["totem.document.create", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.read"], 403),
        ]
    )
    def test_list_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.read"], 200),
            (["totem.document.create", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.read"], 403),
        ]
    )
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), self.document_notes)

    def test_retrieve_response_without_relations(self):
        # The relations unset: null or empty, and the keys still present.
        response = self.do_request("GET", f"{self.url}{DOCUMENT_MINUTES_ID}/")
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, self.document_minutes)
        self.assertEqual((data["user"], data["contact"], data["file"], data["thumbnail"]), (None, None, None, None))

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{DOCUMENT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.read"], 200),
            (["totem.document.create", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.read"], 403),
        ]
    )
    def test_retrieve_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.read"], 200),
            (["totem.document.create", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.read"], 403),
        ]
    )
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            # Located as ninja locates the errors of a multipart request: a form
            # field under `form`, the file part under `file`.
            ("no name for a text", {"name": ""}, None, 422, ["form", "name"]),
            ("no type", {"document_type": None}, None, 422, ["form", "document_type"]),
            ("unknown type", {"document_type": "url"}, None, 422, ["form", "document_type"]),
            ("file without a file", {"document_type": "file", "text_content": None}, None, 422, ["file", "file"]),
            ("file with a text", {"document_type": "file"}, ("map.pdf", pdf_bytes()), 422, ["form", "text_content"]),
            ("text with a file", {}, ("map.pdf", pdf_bytes()), 422, ["file", "file"]),
            (
                "executable file",
                {"document_type": "file", "text_content": None},
                ("logo.svg", b"<svg/>"),
                422,
                ["file", "file"],
            ),
            ("unknown tag", {"tags": ["01JT0000000000000000000099"]}, None, 422, ["form", "tags"]),
            ("unknown contact", {"contact": "01JK0000000000000000000099"}, None, 422, ["form", "contact"]),
            ("malformed date", {"date": "the third age"}, None, 422, ["form", "date"]),
            ("no tag", {"tags": None}, None, 201, None),
            ("file, named after it", {"document_type": "file", "name": None, "text_content": None}, ("map.pdf", pdf_bytes()), 201, None),
        ]
    )
    def test_create_request_field_validation(self, dummy, extra_body, upload, status_code, error_loc):
        data = {**self.payload_create, **extra_body}
        data = {name: value for name, value in data.items() if value is not None}
        if upload:
            data["file"] = SimpleUploadedFile(*upload)

        response = self.do_request("POST", self.url, data=data, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, status_code)
        if error_loc:
            self.assertEqual([detail["loc"][:2] for detail in response.json()["detail"]], [error_loc])
            # Refused before the INSERT: no row, and no file in the storage.
            self.assertEqual(Document.objects.count(), len(ALL_DOCUMENT_IDS))
            self.assertFalse(FileReference.objects.exists())

    def test_create_request_json_body(self):
        # The mistake a client makes first, and it must not half-succeed.
        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(Document.objects.count(), len(ALL_DOCUMENT_IDS))

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create, content_type=MULTIPART_CONTENT)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, Document.objects.get(id=data["id"]))
        self.assertEqual((data["mimetype"], data["size"]), ("text/html", 17))

    def test_create_response_defaults(self):
        # Neither user nor date given: the acting user, and today.
        response = self.do_request(
            "POST", self.url, data={"name": "Letter to Bilbo", "document_type": "text"},
            content_type=MULTIPART_CONTENT,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, Document.objects.get(id=data["id"]))
        self.assertEqual((data["user"]["id"], data["date"]), (str(self.user_frodon.pk), "2026-10-15"))

    def test_create_response_file(self):
        payload = image_bytes(size=(512, 256))
        response = self.do_request(
            "POST", self.url, data={"document_type": "file", "file": SimpleUploadedFile("ring.png", payload)},
            content_type=MULTIPART_CONTENT,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, Document.objects.get(id=data["id"]))
        self.assertEqual((data["name"], data["mimetype"], data["size"]), ("ring.png", "image/png", len(payload)))
        self.assertIsNotNone(data["thumbnail"])

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.create"], 201),
            (["totem.document.read", "totem.document.update", "totem.document.delete"], 403),
            (["totem.documenttag.create"], 403),
        ]
    )
    def test_create_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create, content_type=MULTIPART_CONTENT)

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
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request(
            "POST", self.url, auth="apikey", data=self.payload_create, content_type=MULTIPART_CONTENT
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Default Values Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({}, 200, None),
            ({"fields": "name,date"}, 200, None),
            ({"fields": "id"}, 422, "fields"),  # not a field of the creation
            ({"fields": "mimetype"}, 422, "fields"),  # derived, not a field of the creation
        ]
    )
    def test_default_value_request(self, params, status_code, error_field):
        response = self.do_request("GET", self.url_default_values, params=params)

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand([("user", USER_ID1), ("apikey", None)])  # an API key acts as no user
    def test_default_value_response(self, auth, user_id):
        response = self.do_request("GET", self.url_default_values, auth=auth)

        self.assertEqual(response.status_code, 200)
        self.assert_default_values_format(response.json(), {**DOCUMENT_DEFAULT_VALUES, "user": user_id})

    @parameterized.expand(
        [
            (["date"], ["date"]),
            (["user"], ["user"]),
            (["contact"], ["contact"]),
            # No default: absent, not null.
            (["name"], []),
            (["document_type"], []),
            (["tags"], []),
            (["name", "document_type", *DOCUMENT_DEFAULT_FIELDS], DOCUMENT_DEFAULT_FIELDS),
        ]
    )
    def test_default_value_query_fields(self, query_fields, received_fields):
        response = self.do_request("GET", self.url_default_values, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 200)
        self.assert_default_values_format(response.json(), DOCUMENT_DEFAULT_VALUES, received_fields)

    @parameterized.expand(
        [
            ("user", [], 403),
            ("user", ["totem.document.create"], 200),
            ("user", ["totem.document.read", "totem.document.update", "totem.document.delete"], 403),
            ("user", ["totem.documenttag.create"], 403),
            ("apikey", [], 403),
            ("apikey", ["totem.document.create"], 200),
            ("apikey", ["totem.document.read", "totem.document.update", "totem.document.delete"], 403),
        ]
    )
    def test_default_value_access_rights(self, auth, permissions, status_code):
        if auth == "apikey":
            self.api_key.scope = permissions
            self.api_key.save()
        else:
            self.role.permissions = permissions
            self.role.save()

        response = self.do_request("GET", self.url_default_values, auth=auth)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            ({"tags": ["01JT0000000000000000000099"]}, 422, "tags"),
            ({"contact": "01JK0000000000000000000099"}, 422, "contact"),
            ({"contact": None}, 200, None),
            ({"tags": []}, 200, None),
            ({"text_content": None}, 200, None),
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, Document.objects.get(id=DOCUMENT_NOTES_ID))
        # The size follows the text.
        self.assertEqual((data["name"], data["size"]), ("Notes of the Council", 32))

    def test_update_text_of_a_file_is_refused(self):
        created = self.do_request(
            "POST", self.url, data={"document_type": "file", "file": SimpleUploadedFile("map.pdf", pdf_bytes())},
            content_type=MULTIPART_CONTENT,
        ).json()

        response = self.do_request("PATCH", f"{self.url}{created['id']}/", data={"text_content": "<p>Here</p>"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], ["text_content"])
        self.assertIsNone(Document.objects.get(pk=created["id"]).text_content)

    def test_update_ignores_the_type_and_the_file(self):
        # Not in the update schema: replacing a file means a new document.
        response = self.do_request("PATCH", self.url_detail, data={"document_type": "file", "file": "map.pdf"})

        self.assertEqual(response.status_code, 200)
        document = Document.objects.get(pk=DOCUMENT_NOTES_ID)
        self.assertEqual((document.document_type, document.file.name), ("text", ""))

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{DOCUMENT_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.update"], 200),
            (["totem.document.create", "totem.document.read", "totem.document.delete"], 403),
            (["totem.documenttag.update"], 403),
        ]
    )
    def test_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.update"], 200),
            (["totem.document.create", "totem.document.read", "totem.document.delete"], 403),
            (["totem.documenttag.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Document.objects.filter(pk=DOCUMENT_NOTES_ID).exists())

    def test_delete_response_file(self):
        # The file and its thumbnail go with the document.
        created = self.do_request(
            "POST", self.url, data={"document_type": "file", "file": SimpleUploadedFile("ring.png", image_bytes())},
            content_type=MULTIPART_CONTENT,
        ).json()
        self.assertEqual(FileReference.objects.count(), 2)

        response = self.do_request("DELETE", f"{self.url}{created['id']}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(FileReference.objects.exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{DOCUMENT_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.delete"], 204),
            (["totem.document.create", "totem.document.read", "totem.document.update"], 403),
            (["totem.documenttag.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.document.delete"], 204),
            (["totem.document.create", "totem.document.read", "totem.document.update"], 403),
            (["totem.documenttag.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

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

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or DOCUMENT_FIELDS

        for name in ("id", "name", "document_type", "text_content", "mimetype", "checksum", "size"):
            if name in fields:
                self.assertEqual(api_data[name], getattr(obj, name))
        for name in ("file", "thumbnail"):
            if name in fields:
                stored = getattr(obj, name)
                if stored:
                    # Signed: the signature and its expiry vary, the path does not.
                    self.assertEqual(api_data[name].split("?")[0], stored.storage.url(stored.name).split("?")[0])
                else:
                    self.assertIsNone(api_data[name])
        if "date" in fields:
            self.assertEqual(api_data["date"], obj.date.isoformat() if obj.date else None)
        for name in ("create_date", "update_date"):
            if name in fields:
                self.assertEqual(datetime.fromisoformat(api_data[name]), getattr(obj, name))
        if "user" in fields:
            self.assertEqual(
                api_data["user"], {"id": str(obj.user.pk), "login": obj.user.username} if obj.user else None
            )
        if "contact" in fields:
            self.assertEqual(
                api_data["contact"],
                {"id": obj.contact.pk, "first_name": obj.contact.first_name, "last_name": obj.contact.last_name}
                if obj.contact else None,
            )
        if "tags" in fields:
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

        self.assertEqual(set(fields), set(api_data))

    def assert_default_values_format(self, api_data, values, fields=None):
        fields = DOCUMENT_DEFAULT_FIELDS if fields is None else fields

        for name in fields:
            if name == "user" and values[name] is not None:
                user = User.objects.get(pk=values[name])
                self.assertEqual(api_data[name], {"id": str(user.pk), "login": user.username})
            else:
                self.assertEqual(api_data[name], values[name])

        self.assertEqual(set(fields), set(api_data))
