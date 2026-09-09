import hashlib
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.test.client import MULTIPART_CONTENT

from base.models import FileReference
from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.models import Media

ALL_SCOPES = (
    "totem.websitemedia.create totem.websitemedia.read totem.websitemedia.delete"
)

# A real 1x1 PNG: `Media.precompute_values` guesses the mimetype from the FILE
# NAME, so the bytes only have to be stable, but a genuine image keeps the test
# honest about what the editor actually uploads.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08"
    b"\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\xda\x63\xfc\xcf\xc0"
    b"\xf0\x1f\x00\x05\x00\x01\xff\xab\xce\x36\x89\x00\x00\x00\x00IEND\xaeB`\x82"
)


class MediaAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """The only multipart route in the project.

    Everything the service already covers -- checksum, derived mimetype, the
    filestore symlink -- is tested in test_services/test_media.py. What is worth
    testing HERE is what only the HTTP layer can get wrong: the multipart
    plumbing, the public URL the frontend puts in an `<img src>`, the scopes,
    and the routes that must NOT exist.
    """

    @classmethod
    def setUpClass(cls):
        # Same dance as test_services/test_media: `StorageSettingsMixin` listens
        # on `setting_changed` and drops its cached location, so the module-level
        # storage instances really do follow MEDIA_ROOT. Without it these tests
        # write into the real filestore.
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
        cls.user_access_token_frodon.scope = ALL_SCOPES
        cls.user_access_token_frodon.save()
        cls.url = "/api/v1/website/medias/"

    @property
    def token(self):
        return self.user_access_token_frodon.token

    def _upload(self, filename="diagram.png", payload=PNG, token=None, **kwargs):
        """POST one file as multipart/form-data.

        `content_type` binds to `_do_request`'s own parameter rather than
        landing in **headers, which is what makes the test client encode `data`
        as multipart instead of JSON. No change to core.testing needed.
        """
        return self.do_api_request(
            self.url,
            "POST",
            token if token is not None else self.token,
            data={"content": SimpleUploadedFile(filename, payload, content_type="image/png")},
            content_type=MULTIPART_CONTENT,
            **kwargs,
        )

    # ------------------------------------------
    # Create
    # ------------------------------------------

    def test_create_returns_201(self):
        response = self._upload()
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_returns_the_public_url_in_content(self):
        """The load-bearing assertion for the frontend.

        The rich text editor writes this value straight into an `<img src>`, so
        it has to be the public URL and not the bare stored path. Those are the
        two things `content` can serialise to -- ninja maps a FieldFile to its
        `.url` when serialising an instance, while a list route reads
        `instance.__dict__` and yields the path. This test is what fails if the
        create route ever regresses to the latter.
        """
        data = json.loads(self._upload().content)
        self.assertTrue(
            data["content"].startswith("/media/public/website/"),
            f"expected a public URL, got {data['content']!r}",
        )
        self.assertTrue(data["content"].endswith(".png"), data["content"])
        # Not an equality check on the whole path: MEDIA_ROOT is created once in
        # setUpClass and the filesystem is not rolled back between tests, so
        # Django's `get_available_name` appends a collision suffix as soon as a
        # sibling test has stored the same name. `name` below is the uploaded
        # filename and IS exact.
        self.assertEqual(data["name"], "diagram.png")

    def test_create_derives_name_mimetype_and_checksum(self):
        data = json.loads(self._upload().content)
        self.assertEqual(data["name"], "diagram.png")
        self.assertEqual(data["mimetype"], "image/png")
        self.assertEqual(data["checksum"], hashlib.sha1(PNG).hexdigest())

    def test_create_response_carries_every_schema_field(self):
        # MediaSchema sets `optional_fields = "__all__"`, so a regression to an
        # `exclude_unset` serialisation would silently drop keys the client reads.
        data = json.loads(self._upload().content)
        self.assertEqual(
            set(data),
            {"id", "name", "content", "checksum", "mimetype", "create_date"},
        )

    def test_create_persists_exactly_one_row(self):
        self._upload()
        self.assertEqual(Media.objects.count(), 1)

    def test_upload_is_filed_under_its_own_checksum(self):
        """The `seek(0)` regression, at the HTTP layer.

        Not redundant with the service test that asserts the same thing: this
        stream came through Django's real multipart parser, so it is an
        `InMemoryUploadedFile`/`TemporaryUploadedFile` rather than a
        `SimpleUploadedFile`, and it may arrive with a non-zero cursor.
        `MediaQuerySet.bulk_create` rewinds precisely because
        `PublicMediaFileSystemStorage._save` reads the stream again and never
        does; a cursor left at EOF files every upload under the SHA1 of b"".
        """
        media = Media.objects.get(pk=json.loads(self._upload().content)["id"])
        reference = FileReference.objects.get(symbolic_path=media.content.name)
        self.assertEqual(reference.checksum, hashlib.sha1(PNG).hexdigest())
        self.assertNotEqual(reference.checksum, hashlib.sha1(b"").hexdigest())

    def test_two_uploads_of_the_same_bytes_share_one_stored_file(self):
        # Only a second upload of identical bytes reaches the content-addressed
        # `if not self.exists(store_path)` branch and the upsert behind it.
        first = json.loads(self._upload(filename="a.png").content)
        second = json.loads(self._upload(filename="b.png").content)
        self.assertEqual(first["checksum"], second["checksum"])
        self.assertEqual(Media.objects.count(), 2)
        # One FileReference PER SYMLINK -- the model is unique on
        # (privacy, symbolic_path) -- but both point at a single stored blob,
        # which is where the content addressing pays off.
        paths = set(
            FileReference.objects.filter(checksum=first["checksum"]).values_list(
                "store_path", flat=True
            )
        )
        self.assertEqual(len(paths), 1, paths)

    # ------------------------------------------
    # Create -- refusals
    # ------------------------------------------

    def test_create_without_a_file_is_422(self):
        # The error shape the frontend's parseApiError reads: it takes the LAST
        # element of `loc`, which must be the field name the client sent.
        response = self.do_api_request(
            self.url, "POST", self.token, data={}, content_type=MULTIPART_CONTENT
        )
        self.assertEqual(response.status_code, 422, response.content)
        detail = json.loads(response.content)["detail"]
        self.assertEqual(detail[0]["loc"], ["file", "content"])
        self.assertEqual(detail[0]["type"], "missing")

    def test_create_with_a_json_body_is_refused(self):
        # The mistake a client makes first, and it must not half-succeed.
        response = self.do_api_request(
            self.url, "POST", self.token, data={"content": "website/x.png"}
        )
        self.assertIn(response.status_code, (400, 422), response.content)
        self.assertEqual(Media.objects.count(), 0)

    def test_create_rejects_an_oversized_file(self):
        from website.services import MediaService

        oversized = b"x" * (MediaService.MAX_UPLOAD_SIZE + 1)
        response = self._upload(filename="huge.png", payload=oversized)
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(json.loads(response.content)["detail"][0]["loc"][-1], "content")
        # Rejected BEFORE the INSERT and before the bytes are committed.
        self.assertEqual(Media.objects.count(), 0)
        self.assertEqual(FileReference.objects.count(), 0)

    def test_create_rejects_a_file_that_would_execute_when_served(self):
        # An SVG is served from /media/public/ on our own origin with no CSP.
        response = self._upload(filename="payload.svg", payload=b"<svg onload='x()'/>")
        self.assertEqual(response.status_code, 422, response.content)
        self.assertEqual(json.loads(response.content)["detail"][0]["loc"][-1], "content")
        self.assertEqual(Media.objects.count(), 0)

    def test_create_still_accepts_a_document(self):
        # `Media` is a general file store, not an image store: the admin form and
        # the service tests both file PDFs through it. Narrowing it to images to
        # suit the editor would be a regression, so it is pinned here.
        response = self._upload(filename="report.pdf", payload=b"%PDF-1.4")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(json.loads(response.content)["mimetype"], "application/pdf")

    def test_create_without_the_scope_is_403(self):
        self.user_access_token_frodon.scope = "totem.websitemedia.read"
        self.user_access_token_frodon.save()
        self.assertEqual(self._upload().status_code, 403)

    def test_create_without_a_token_is_401(self):
        # Django's client directly: `do_api_request` builds the header by
        # concatenating the token, so it cannot express "no token at all".
        response = Client().post(
            self.url,
            data={"content": SimpleUploadedFile("x.png", PNG)},
            content_type=MULTIPART_CONTENT,
        )
        self.assertEqual(response.status_code, 401)

    # ------------------------------------------
    # Retrieve / Delete
    # ------------------------------------------

    def test_retrieve_returns_the_same_public_url_as_create(self):
        created = json.loads(self._upload().content)
        response = self.do_api_request(f"{self.url}{created['id']}/", "GET", self.token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(json.loads(response.content)["content"], created["content"])

    def test_retrieve_unknown_id_is_404(self):
        response = self.do_api_request(f"{self.url}01ARZ3NDEKTSV4RRFFQ69G5FAV/", "GET", self.token)
        self.assertEqual(response.status_code, 404)

    def test_delete_removes_the_row_and_the_stored_file(self):
        created = json.loads(self._upload().content)
        media = Media.objects.get(pk=created["id"])
        stored = media.content.name

        response = self.do_api_request(f"{self.url}{created['id']}/", "DELETE", self.token)
        self.assertEqual(response.status_code, 204, response.content)
        self.assertEqual(Media.objects.count(), 0)
        # CleanupFileQuerysetMixin.delete is what reference-counts the filestore.
        self.assertFalse(FileReference.objects.filter(symbolic_path=stored).exists())

    def test_delete_without_the_scope_is_403(self):
        """The guard on a hole that is easy to reopen.

        `DeleteModelControllerMixin.add_routes_to` is guarded by `if cls.model:`
        alone -- it has no schema switch -- so inheriting it always registers
        DELETE, and `_get_action_permissions` returns [] for a missing
        `permission_map` key. Dropping the "delete" entry would therefore leave
        this route open to any authenticated token, with no other test noticing.
        """
        created = json.loads(self._upload().content)
        self.user_access_token_frodon.scope = "totem.websitemedia.read"
        self.user_access_token_frodon.save()
        response = self.do_api_request(f"{self.url}{created['id']}/", "DELETE", self.token)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Media.objects.count(), 1)

    # ------------------------------------------
    # List
    # ------------------------------------------

    def _list(self, query="", token=None):
        return json.loads(
            self.do_api_request(
                f"{self.url}{query}", "GET", token if token is not None else self.token
            ).content
        )

    def test_list_returns_the_pagination_envelope(self):
        self._upload()
        data = self._list()
        self.assertEqual(set(data), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], 1)

    def test_list_row_carries_exactly_the_picker_fields(self):
        """The narrowing is the contract, not an implementation detail.

        `MediaListSchema` is not `MediaSchema`: a picker shows a thumbnail, a
        caption and a type. `checksum` and `create_date` are not in it, and a
        regression to the wider schema would publish a lookup key nobody asked
        for on a route with a search box.
        """
        self._upload()
        row = self._list()["results"][0]
        self.assertEqual(set(row), {"id", "name", "content", "mimetype"})
        self.assertEqual(row["name"], "diagram.png")
        self.assertEqual(row["mimetype"], "image/png")

    def test_list_returns_the_public_url_in_content(self):
        """The load-bearing assertion for the image picker.

        Every row becomes an `<img src>` in a thumbnail grid. A list route
        serialises `instance.__dict__`, which holds the bare stored path -- so
        without `MediaListSchema._stored_path_to_url` every thumbnail 404s. This
        is the test that fails if that validator is dropped or stops firing
        (pydantic silently ignores a validator whose field it cannot find).
        """
        created = json.loads(self._upload().content)
        row = self._list()["results"][0]
        self.assertTrue(
            row["content"].startswith("/media/public/website/"),
            f"expected a public URL, got {row['content']!r}",
        )
        # And the SAME url the create route answered: one media, one address.
        self.assertEqual(row["content"], created["content"])

    def test_list_search_matches_the_name(self):
        self._upload(filename="winter-diagram.png")
        self._upload(filename="summer-photo.png")

        names = [row["name"] for row in self._list("?search=diagram")["results"]]
        self.assertEqual(names, ["winter-diagram.png"])

    def test_list_search_is_case_insensitive_and_partial(self):
        self._upload(filename="Winter-Diagram.png")
        self.assertEqual(self._list("?search=inter-dia")["count"], 1)

    def test_list_search_matches_nothing_else(self):
        """`search` is the name, and only the name.

        The service's own `MediaFilterSchema` also filters on mimetype and
        checksum; `MediaListFilterSchema` deliberately does not, so a search box
        cannot be used to probe the filestore for a known file.
        """
        self._upload(filename="photo.png")
        self.assertEqual(self._list("?search=image/png")["count"], 0)
        self.assertEqual(self._list(f"?search={hashlib.sha1(PNG).hexdigest()}")["count"], 0)

    def test_list_ignores_an_undeclared_filter(self):
        """An unknown query param narrows nothing -- it does not 422 either.

        Worth pinning rather than assuming: ninja simply does not bind a param
        the FilterSchema does not declare. So dropping a field from
        `MediaListFilterSchema` really does remove the lookup, instead of
        leaving it silently working through some other path.
        """
        self._upload(filename="photo.png")
        checksum = hashlib.sha1(PNG).hexdigest()

        for query in (f"?checksum={checksum}", "?mimetype=image/png", "?name=nothing"):
            data = self._list(query)
            self.assertEqual(data["count"], 1, f"{query} filtered something")

    def test_list_paginates(self):
        for index in range(3):
            self._upload(filename=f"page-{index}.png")

        first = self._list("?page_size=2")
        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["results"]), 2)
        self.assertIsNotNone(first["next"])

        second = self._list("?page_size=2&page=2")
        self.assertEqual(len(second["results"]), 1)
        self.assertIsNone(second["next"])

    def test_list_returns_the_newest_first(self):
        # `-create_date` by default: a picker opens on what was just uploaded.
        for index in range(3):
            self._upload(filename=f"shot-{index}.png")

        names = [row["name"] for row in self._list()["results"]]
        self.assertEqual(names, ["shot-2.png", "shot-1.png", "shot-0.png"])

    def test_list_without_the_scope_is_403(self):
        self.user_access_token_frodon.scope = "totem.websitemedia.create"
        self.user_access_token_frodon.save()
        response = self.do_api_request(self.url, "GET", self.token)
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------
    # The routes that must not exist
    # ------------------------------------------

    def test_there_is_no_update_route(self):
        # A media is immutable: replacing the bytes is a create plus a delete,
        # which is what keeps `checksum` honest.
        created = json.loads(self._upload().content)
        response = self.do_api_request(f"{self.url}{created['id']}/", "PATCH", self.token)
        self.assertEqual(response.status_code, 405, response.content)
