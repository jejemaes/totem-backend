import datetime
import hashlib
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.test.client import MULTIPART_CONTENT
from parameterized import parameterized

from authentication.testing import mint_access_token
from base.models import FileReference
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes
from website.models import Media
from website.services import MediaService

from .common import MEDIA_SCOPES, PERMISSION_DENIED, CommonTestMixin

MEDIA_ID1 = "01M209K5BNS12QRPHXFWVJNVX1"
MEDIA_ID2 = "01M209K5BNS12QRPHXFWVJNVX2"
MEDIA_ID3 = "01M209K5BNS12QRPHXFWVJNVX3"
MEDIA_ID4 = "01ARZ3NDEKTSV4RRFFQ69G5FAV"  # matches no media

ALL_MEDIA_IDS = [MEDIA_ID1, MEDIA_ID2, MEDIA_ID3]

# The detail routes (retrieve, create) answer `MediaSchema`; the list answers
# the narrower `MediaListSchema` of the picker.
MEDIA_FIELDS = ["id", "name", "content", "checksum", "mimetype", "create_date"]
MEDIA_LIST_FIELDS = ["id", "name", "content", "mimetype"]

# A real 1x1 PNG: `Media.precompute_values` guesses the mimetype from the FILE
# NAME, so the bytes only have to be stable, but a genuine image keeps the test
# honest about what the editor actually uploads.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xda\x63\xfc\xcf\xc0"
    b"\xf0\x1f\x00\x05\x00\x01\xff\xab\xce\x36\x89\x00\x00\x00\x00IEND\xaeB`\x82"
)


class MediaAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ List, retrieve, create (multipart) and delete. No update: a media is
    immutable, replacing the bytes is a create plus a delete, which is what keeps
    `checksum` honest -- and that absence is asserted below.

    No `*_access_rules` tests: no `BaseRule` is registered for `Media`, so there
    is no rule a role could hold to narrow it.

    Everything the service already covers -- checksum, derived mimetype, the
    filestore symlink -- is tested in test_services/test_media.py. What is worth
    testing HERE is what only the HTTP layer can get wrong: the multipart
    plumbing, the public URL the frontend puts in an `<img src>`, the scopes,
    and the routes that must NOT exist.
    """

    @classmethod
    def setUpClass(cls):
        # `StorageSettingsMixin` listens on `setting_changed` and drops its cached
        # location, so the module-level storage instances really do follow
        # MEDIA_ROOT. Without it these tests write into the real filestore.
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # A checksum given: no file to read, nothing written to storage. Created
        # in order, so `create_date` grows with the ids.
        cls.media_map, cls.media_book, cls.media_gate = Media.objects.bulk_create([
            Media(
                id=MEDIA_ID1, name="map-of-the-shire.png", content="website/map-of-the-shire.png",
                mimetype="image/png", checksum="a" * 40,
            ),
            Media(
                id=MEDIA_ID2, name="red-book-of-westmarch.pdf", content="website/red-book-of-westmarch.pdf",
                mimetype="application/pdf", checksum="b" * 40,
            ),
            Media(
                id=MEDIA_ID3, name="moria-gate.png", content="website/moria-gate.png",
                mimetype="image/png", checksum="c" * 40,
            ),
        ])

        cls.role.permissions = MEDIA_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/website/medias/"
        cls.url_detail = f"/api/v1/website/medias/{MEDIA_ID1}/"

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_MEDIA_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_MEDIA_IDS))

        # `MediaListSchema` is not `MediaSchema`: `checksum` and `create_date`
        # are not in a row of the picker, and the key-set assertion is what
        # fails if the list regresses to the wider schema.
        for item in data["results"]:
            self.assert_api_format(item, Media.objects.get(pk=item["id"]), MEDIA_LIST_FIELDS)

    def test_list_response_public_url(self):
        """The load-bearing assertion for the image picker.

        Every row becomes an `<img src>` in a thumbnail grid. A list route
        serialises `instance.__dict__`, which holds the bare stored path -- so
        without `MediaListSchema._stored_path_to_url` every thumbnail 404s. This
        is the test that fails if that validator is dropped or stops firing
        (pydantic silently ignores a validator whose field it cannot find).
        """
        response = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )
        created = response.json()

        rows = {item["id"]: item for item in self.do_request("GET", self.url).json()["results"]}

        self.assertTrue(rows[created["id"]]["content"].startswith("/media/public/website/"))
        # And the SAME url the create route answered: one media, one address.
        self.assertEqual(rows[created["id"]]["content"], created["content"])

    @parameterized.expand(
        [
            # `search` is the only filter of `MediaListFilterSchema`, and it has
            # its own test. Any other param is not bound by ninja: it narrows
            # nothing and does not 422 either. So dropping a field from the
            # schema really does remove the lookup -- in particular `checksum`,
            # which the service's own `MediaFilterSchema` has, and which would
            # let a caller probe the filestore for a known file.
            ({"checksum": "a" * 40},),
            ({"mimetype": "application/pdf"},),
            ({"name": "mordor"},),
        ]
    )
    def test_list_filters(self, filters):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, set(ALL_MEDIA_IDS))

    # No `test_list_invalid_filters`: the only filter, `search`, is a string, so
    # no value can fail to parse.

    @parameterized.expand(
        [
            # `-create_date` by default: a picker opens on what was just uploaded.
            ([], ["-create_date", "id"]),
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["create_date"], ["create_date", "id"]),
            (["-create_date"], ["-create_date", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in Media.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    @parameterized.expand(
        [
            ([], MEDIA_LIST_FIELDS),  # default means all the fields of the list
            (["name"], ["id", "name"]),  # `id` is always returned
            (["content", "mimetype"], ["id", "content", "mimetype"]),
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_MEDIA_IDS))
        for item in data["results"]:
            self.assert_api_format(item, Media.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "name"],),
            # In `MediaSchema`, not in the list's: the narrowing holds for
            # `fields` too.
            (["checksum"],),
            (["create_date"],),
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("shire", [MEDIA_ID1]),
            ("MORIA-g", [MEDIA_ID3]),  # case insensitive and partial
            (".png", [MEDIA_ID1, MEDIA_ID3]),
            ("mordor", []),
            # `search` is the name, and only the name: neither the mimetype nor
            # the checksum.
            ("image/png", []),
            ("a" * 40, []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

    @parameterized.expand(
        [
            ({"page_size": 2}, [MEDIA_ID3, MEDIA_ID2], True),
            ({"page_size": 2, "page": 2}, [MEDIA_ID1], False),
        ]
    )
    def test_list_pagination(self, params, expected_pks, has_next):
        response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_MEDIA_IDS))
        self.assertEqual([item["id"] for item in data["results"]], expected_pks)
        self.assertEqual(data["next"] is not None, has_next)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.read"], 200),
            (["totem.websitemedia.create", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.read"], 403),
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
            (["totem.websitemedia.read"], 200),
            (["totem.websitemedia.create", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.read"], 403),
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
        self.assert_api_format(response.json(), self.media_map)

    def test_retrieve_response_public_url(self):
        # The same public URL as the create route answered.
        created = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        ).json()

        response = self.do_request("GET", f"{self.url}{created['id']}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], created["content"])

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{MEDIA_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.read"], 200),
            (["totem.websitemedia.create", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.read"], 403),
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
            (["totem.websitemedia.read"], 200),
            (["totem.websitemedia.create", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.read"], 403),
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
            ("map.png", PNG, 201, None),
            # `Media` is a general file store, not an image store: the admin form
            # and the service tests both file PDFs through it. Narrowing it to
            # images to suit the editor would be a regression.
            ("red-book.pdf", b"%PDF-1.4", 201, None),
            # Served from /media/public/ on our own origin with no CSP.
            ("payload.svg", b"<svg onload='x()'/>", 422, "content"),
            # Refused BEFORE the INSERT and before the bytes are committed.
            ("huge.png", b"x" * (MediaService.MAX_UPLOAD_SIZE + 1), 422, "content"),
            # No file part at all.
            (None, None, 422, "content"),
        ]
    )
    def test_create_request_field_validation(self, filename, payload, status_code, error_field):
        data = {"content": SimpleUploadedFile(filename, payload)} if filename else {}

        response = self.do_request("POST", self.url, data=data, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            # The error shape the frontend's parseApiError reads: it takes the
            # LAST element of `loc`, which must be the field name the client sent.
            self.assertEqual(response.json()["detail"][0]["loc"][-1], error_field)
            self.assertEqual(Media.objects.count(), len(ALL_MEDIA_IDS))
            self.assertEqual(FileReference.objects.count(), 0)

    def test_create_request_without_a_file_part(self):
        response = self.do_request("POST", self.url, data={}, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertEqual(detail[0]["loc"], ["file", "content"])
        self.assertEqual(detail[0]["type"], "missing")

    def test_create_request_json_body(self):
        # The mistake a client makes first, and it must not half-succeed.
        response = self.do_request("POST", self.url, data={"content": "website/x.png"})

        self.assertIn(response.status_code, (400, 422))
        self.assertEqual(Media.objects.count(), len(ALL_MEDIA_IDS))

    def test_create_response(self):
        response = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, Media.objects.get(pk=data["id"]))
        # Derived from the upload, none of them sent by the client.
        self.assertEqual(data["name"], "rivendell.png")
        self.assertEqual(data["mimetype"], "image/png")
        self.assertEqual(data["checksum"], hashlib.sha1(PNG).hexdigest())
        self.assertEqual(Media.objects.count(), len(ALL_MEDIA_IDS) + 1)

    def test_create_response_public_url(self):
        """The load-bearing assertion for the frontend.

        The rich text editor writes this value straight into an `<img src>`, so
        it has to be the public URL and not the bare stored path. Not an
        equality check on the whole path: MEDIA_ROOT is created once in
        setUpClass and the filesystem is not rolled back between tests, so
        Django's `get_available_name` appends a collision suffix as soon as a
        sibling test has stored the same name.
        """
        response = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["content"].startswith("/media/public/website/"))
        self.assertTrue(response.json()["content"].endswith(".png"))

    def test_create_filed_under_its_own_checksum(self):
        """The `seek(0)` regression, at the HTTP layer.

        Not redundant with the service test asserting the same thing: this
        stream came through Django's real multipart parser, so it is an
        `InMemoryUploadedFile`/`TemporaryUploadedFile` rather than a
        `SimpleUploadedFile`, and it may arrive with a non-zero cursor.
        `MediaQuerySet.bulk_create` rewinds precisely because
        `PublicMediaFileSystemStorage._save` reads the stream again and never
        does; a cursor left at EOF files every upload under the SHA1 of b"".
        """
        response = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )

        media = Media.objects.get(pk=response.json()["id"])
        reference = FileReference.objects.get(symbolic_path=media.content.name)
        self.assertEqual(reference.checksum, hashlib.sha1(PNG).hexdigest())
        self.assertNotEqual(reference.checksum, hashlib.sha1(b"").hexdigest())

    def test_create_same_bytes_share_one_stored_file(self):
        # Only a second upload of identical bytes reaches the content-addressed
        # `if not self.exists(store_path)` branch and the upsert behind it.
        first = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("lothlorien.png", PNG)},
            content_type=MULTIPART_CONTENT,
        ).json()
        second = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("isengard.png", PNG)},
            content_type=MULTIPART_CONTENT,
        ).json()

        self.assertEqual(first["checksum"], second["checksum"])
        # One FileReference PER SYMLINK -- the model is unique on
        # (privacy, symbolic_path) -- but both point at a single stored blob,
        # which is where the content addressing pays off.
        store_paths = set(
            FileReference.objects.filter(checksum=first["checksum"]).values_list("store_path", flat=True)
        )
        self.assertEqual(len(store_paths), 1)

    def test_create_without_a_credential(self):
        # Django's client directly: `do_request` always authenticates, so it
        # cannot express "no credential at all".
        response = Client().post(
            self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )

        self.assertEqual(response.status_code, 401)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.create"], 201),
            (["totem.websitemedia.read", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.create"], 403),
        ]
    )
    def test_create_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.create"], 201),
            (["totem.websitemedia.read", "totem.websitemedia.delete"], 403),
            (["totem.websitepage.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request(
            "POST", self.url, auth="apikey", data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ("PATCH",),
            ("PUT",),
        ]
    )
    def test_update_route_does_not_exist(self, method):
        # A media is immutable: replacing the bytes is a create plus a delete,
        # which is what keeps `checksum` honest.
        response = self.do_request(method, self.url_detail)

        self.assertEqual(response.status_code, 405)
        self.assertEqual(Media.objects.get(pk=MEDIA_ID1).name, "map-of-the-shire.png")

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(Media.objects.filter(pk=MEDIA_ID1).exists())

    def test_delete_removes_the_stored_file(self):
        created = self.do_request(
            "POST", self.url, data={"content": SimpleUploadedFile("rivendell.png", PNG)},
            content_type=MULTIPART_CONTENT,
        ).json()
        stored = Media.objects.get(pk=created["id"]).content.name

        response = self.do_request("DELETE", f"{self.url}{created['id']}/")

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Media.objects.filter(pk=created["id"]).exists())
        # `CleanupFileQuerysetMixin.delete` is what reference-counts the filestore.
        self.assertFalse(FileReference.objects.filter(symbolic_path=stored).exists())

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{MEDIA_ID4}/")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Media.objects.count(), len(ALL_MEDIA_IDS))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.delete"], 204),
            # The guard on a hole that is easy to reopen: `DeleteModelControllerMixin`
            # always registers DELETE, and a missing `permission_map` key means no
            # scope at all. Dropping "delete" would leave this route open to any
            # credential, with no other test noticing.
            (["totem.websitemedia.create", "totem.websitemedia.read"], 403),
            (["totem.websitepage.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Media.objects.filter(pk=MEDIA_ID1).exists(), status_code != 204)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.websitemedia.delete"], 204),
            (["totem.websitemedia.create", "totem.websitemedia.read"], 403),
            (["totem.websitepage.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Media.objects.filter(pk=MEDIA_ID1).exists(), status_code != 204)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None, content_type=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would. `content_type=MULTIPART_CONTENT`
        binds to `_do_request`'s own parameter, which is what makes the test
        client encode `data` as multipart instead of JSON.
        """
        extra = {"content_type": content_type} if content_type else {}
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {}, **extra)
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {}, **extra)

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or MEDIA_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.pk))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "content" in fields:
            # The public URL, on every route: never the bare stored path.
            self.assertEqual(api_data["content"], obj.content.url)
        if "checksum" in fields:
            self.assertEqual(api_data["checksum"], obj.checksum)
        if "mimetype" in fields:
            self.assertEqual(api_data["mimetype"], obj.mimetype)
        if "create_date" in fields:
            # Serialized to the millisecond, as every datetime of the API.
            self.assertEqual(
                datetime.datetime.fromisoformat(api_data["create_date"]),
                obj.create_date.replace(microsecond=obj.create_date.microsecond // 1000 * 1000),
            )

        self.assertEqual(set(fields), set(api_data))
