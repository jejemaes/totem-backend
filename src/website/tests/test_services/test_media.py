import hashlib
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from base.models import FileReference
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from website.models import Media
from website.schemas import MediaCreateSchema, MediaFilterSchema
from website.services import MediaService

from website.tests.test_services.common_media import (
    MEDIA_BOOK_ID,
    MEDIA_MAP_ID,
    MEDIA_UNKNOWN_ID,
    PAYLOAD,
    PAYLOAD_SHA1,
    MediaServiceCommonMixin,
    upload,
)


class MediaServiceTest(MediaServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `MediaService`: create, read, delete. A media is immutable: no update,
    replacing the bytes is a create and a delete. `checksum`, `mimetype` and
    `name` are derived by `MediaQuerySet.bulk_create`.

    No access rules tests: no `BaseRule` is registered for `Media`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(MediaService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # The mimetype is guessed from the filename; the name is the one of
            # the upload, captured before `FileField.pre_save` replaces it with
            # the stored path.
            ("a document", "red-book.pdf", PAYLOAD, "application/pdf"),
            ("an image", "map.png", b"\x89PNG not really", "image/png"),
            # NOT an allow-list: `Media` is a general file store.
            ("an archive", "maps.zip", b"PK not really", "application/zip"),
        ]
    )
    def test_create(self, label, filename, payload, mimetype):
        # The roles, the transaction, the file reference, the insert, and the
        # access rules checked on the rows written.
        with self.assertNumQueries(6):
            instances = async_to_sync(self.service.create)([MediaCreateSchema(content=upload(filename, payload))])

        self.assertEqual(len(instances), 1)
        media = Media.objects.get(pk=instances[0].pk)
        self.assertEqual(
            (media.name, media.mimetype, media.checksum),
            (filename, mimetype, hashlib.sha1(payload).hexdigest()),
        )
        # A `FileField` holds the *symlink* path: the storage keeps the bytes once,
        # under `_filestore/<sha1>`, and points a symlink at them.
        self.assertTrue(media.content.name.startswith("website/"))
        self.assertTrue(media.content.storage.symlink_exists(media.content.name))
        # Regression guard for the mandatory `seek(0)`: the storage reads the
        # stream again and never rewinds, so a cursor left at the end files
        # every upload under the SHA1 of the empty string.
        reference = FileReference.objects.get(symbolic_path=media.content.name)
        self.assertEqual(reference.checksum, hashlib.sha1(payload).hexdigest())

    @parameterized.expand(
        [
            # `validate_upload`, keyed by the index of the payload, before the
            # INSERT: nothing reaches the storage.
            ("an executable type", "map.svg", b"<svg/>", None, "content"),
            ("an html file", "red-book.html", b"<p/>", None, "content"),
            ("too large", "red-book.pdf", PAYLOAD, len(PAYLOAD) - 1, "content"),
        ]
    )
    def test_create_invalid(self, label, filename, payload, max_size, error_key):
        with patch.object(MediaService, "MAX_UPLOAD_SIZE", max_size or MediaService.MAX_UPLOAD_SIZE):
            with self.assertNumQueries(4):
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)([MediaCreateSchema(content=upload(filename, payload))])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Media.objects.count(), 2)
        self.assertFalse(FileReference.objects.exists())

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([{"content": upload()}])

        self.assertEqual(Media.objects.count(), 2)

    # No `test_create_relations`: a media has no relation to write.

    @parameterized.expand(
        [
            # Two uploads of different bytes are filed apart.
            ("every input valid", [("a.pdf", b"first"), ("b.pdf", b"second")], 7, None),
            # All or nothing: the valid first upload is not written either.
            ("the second input invalid", [("a.pdf", b"first"), ("b.svg", b"<svg/>")], 4, {1: ["content"]}),
        ]
    )
    def test_create_batch(self, label, files, query_count, errors):
        data = [MediaCreateSchema(content=upload(filename, payload)) for filename, payload in files]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual([media.name for media in instances], ["a.pdf", "b.pdf"])
            self.assertEqual(len(set(FileReference.objects.values_list("store_path", flat=True))), 2)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertEqual(Media.objects.count(), 2)
            self.assertFalse(FileReference.objects.exists())

    def test_default_values(self):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(None)

        self.assertEqual({name: value for name, value in values.items() if value is not None}, {})

    @parameterized.expand([("update",), ("resequence",)])
    def test_operation_is_not_composed(self, operation):
        # A media is immutable: replacing the bytes is a create plus a delete.
        self.assertFalse(hasattr(MediaService, operation))

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, [MEDIA_MAP_ID, MEDIA_BOOK_ID]),
            # The filter schema of the service: `checksum` looks a known file up.
            ("by checksum", MediaFilterSchema(checksum="b" * 40), [MEDIA_BOOK_ID]),
            ("by mimetype", MediaFilterSchema(mimetype="image"), [MEDIA_MAP_ID]),
            ("by a search term", MediaFilterSchema(search="shire"), [MEDIA_MAP_ID]),
            ("nothing matches", MediaFilterSchema(name="palantir"), []),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = [media.pk for media in async_to_sync(self.service.read)(filters)]

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by name", ["name"], [MEDIA_MAP_ID, MEDIA_BOOK_ID]),
            ("by mimetype, descending", ["-mimetype"], [MEDIA_MAP_ID, MEDIA_BOOK_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [media.pk for media in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    def test_read_fields(self):
        with self.assertNumQueries(2):
            medias = list(async_to_sync(self.service.read)({"id": MEDIA_MAP_ID}, fields=["id", "name", "mimetype"]))

        self.assertEqual([(media.name, media.mimetype) for media in medias], [("map-of-the-shire.png", "image/png")])
        self.assertIn("checksum", medias[0].get_deferred_fields())

    def test_read_the_checksum_of_an_upload(self):
        media = async_to_sync(self.service.create)([MediaCreateSchema(content=upload())])[0]

        pks = [found.pk for found in async_to_sync(self.service.read)(MediaFilterSchema(checksum=PAYLOAD_SHA1))]

        self.assertEqual(pks, [media.pk])

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    def test_delete(self):
        media = Media.objects.get(pk=async_to_sync(self.service.create)([MediaCreateSchema(content=upload())])[0].pk)
        storage, path = media.content.storage, media.content.name

        with self.assertNumQueries(8):
            count = async_to_sync(self.service.delete)({"id": media.pk})

        self.assertEqual(count, 1)
        self.assertFalse(Media.objects.filter(pk=media.pk).exists())
        # `CleanupFileQuerysetMixin.delete` reaches the storage, which drops the
        # symlink and -- no other reference left -- the bytes.
        self.assertFalse(storage.symlink_exists(path))
        self.assertFalse(FileReference.objects.filter(symbolic_path=path).exists())

    def test_delete_keeps_the_bytes_another_media_shares(self):
        # The same bytes twice: one file in the store, two references to it.
        first, second = async_to_sync(self.service.create)(
            [MediaCreateSchema(content=upload("a.pdf")), MediaCreateSchema(content=upload("b.pdf"))]
        )
        second = Media.objects.get(pk=second.pk)

        async_to_sync(self.service.delete)({"id": first.pk})

        self.assertTrue(second.content.storage.symlink_exists(second.content.name))
        self.assertEqual(FileReference.objects.count(), 1)

    def test_delete_not_found(self):
        with self.assertNumQueries(5):
            count = async_to_sync(self.service.delete)({"id": MEDIA_UNKNOWN_ID})

        self.assertEqual(count, 0)
        self.assertEqual(Media.objects.count(), 2)
