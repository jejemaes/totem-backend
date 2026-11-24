import hashlib
from datetime import date
from unittest.mock import patch
from uuid import UUID

from asgiref.sync import async_to_sync
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized
from PIL import Image

from base.models import FileReference
from core.services.exceptions import ServiceValidationMultiError
from core.testing import ServiceTestCaseMixin
from document.choices import DocumentType
from document.models import Document
from document.schemas import DocumentCreateSchema, DocumentFilterSchema, DocumentUpdateSchema
from document.services import DocumentService
from document.tests.images import image_bytes, jpeg_rotated_bytes, pdf_bytes
from user.tests.test_services.common_user import USER_FRODON_ID, USER_SAM_ID

from document.tests.test_services.common_document import (
    CONTACT_ELROND_ID,
    CONTACT_GALADRIEL_ID,
    DOCUMENT_MINUTES_ID,
    DOCUMENT_NOTES_ID,
    DOCUMENT_UNKNOWN_ID,
    PAYLOAD,
    DocumentServiceCommonMixin,
    upload,
)
from document.tests.test_services.common_document_tag import TAG_2026_ID, TAG_DRAFT_ID, TAG_SIGNED_ID, TAG_UNKNOWN_ID
from document.tests.test_services.common_document_tag_category import CATEGORY_STATUS_ID, CATEGORY_YEAR_ID

ALL_DOCUMENT_IDS = [DOCUMENT_NOTES_ID, DOCUMENT_MINUTES_ID]

USER_UNKNOWN_ID = "5263de93-e694-41ef-b873-34610551afcd"

TEXT = {"name": "Letter to Bilbo", "document_type": DocumentType.TEXT}


class DocumentServiceTest(DocumentServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ `DocumentService`: create, read, update, delete and default values.
    `upload` has its own file.

    `mimetype`, `checksum`, `size` and `thumbnail` are derived from the content
    before the INSERT, which is also where the file is committed to storage: a
    refused write leaves neither a row nor a `FileReference` behind.

    No access rules tests: no `BaseRule` is registered for `Document`.
    """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(DocumentService, user=self.user_frodon)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            # Named after the file by default; derived from the bytes. The roles,
            # the owner, the transaction, the insert, the access rules checked on
            # the rows written; and for a file, its reference and its thumbnail's.
            (
                "a file",
                {"document_type": DocumentType.FILE, "file": "map.pdf"},
                8,
                {"name": "map.pdf", "mimetype": "application/pdf", "checksum": hashlib.sha1(PAYLOAD).hexdigest(), "size": len(PAYLOAD), "text_content": None},
            ),
            ("a file with a name", {"name": "Map of the Shire", "document_type": DocumentType.FILE, "file": "map.pdf"}, 8, {"name": "Map of the Shire"}),
            # In bytes: two for "é" in UTF-8. No checksum, no file.
            ("a text", {**TEXT, "text_content": "<p>Élessar</p>"}, 6, {"mimetype": "text/html", "size": 15, "checksum": None}),
            ("an empty text", TEXT, 6, {"size": 0, "text_content": None}),
            (
                "a text with relations",
                {**TEXT, "date": "2026-03-25", "user": USER_SAM_ID, "contact": CONTACT_GALADRIEL_ID, "tags": [TAG_DRAFT_ID, TAG_2026_ID]},
                9,
                {"date": date(2026, 3, 25), "user_id": UUID(USER_SAM_ID), "contact_id": CONTACT_GALADRIEL_ID},
            ),
            # The user defaults to the acting user, announced as applied.
            ("the user left out", TEXT, 6, {"user_id": UUID(USER_FRODON_ID)}),
            # Given, even as null, a field is never overwritten by its default.
            ("a user set to null", {**TEXT, "user": None}, 5, {"user_id": None}),
            ("a date set to null", {**TEXT, "date": None}, 6, {"date": None}),
        ]
    )
    def test_create(self, label, payload, query_count, expected_values):
        if "file" in payload:
            payload = {**payload, "file": upload(payload["file"])}

        with self.assertNumQueries(query_count):
            instances = async_to_sync(self.service.create)([DocumentCreateSchema(**payload)])

        self.assertEqual(len(instances), 1)
        document = Document.objects.get(pk=instances[0].pk)
        self.assertEqual({name: getattr(document, name) for name in expected_values}, expected_values)
        self.assertCountEqual(document.tags.values_list("pk", flat=True), payload.get("tags", []))
        if document.document_type == DocumentType.FILE:
            # The storage filed the uploaded bytes, not the empty rest of a stream
            # left at its end: it was rewound after being read for the checksum.
            self.assertEqual(FileReference.objects.get(symbolic_path=document.file.name).checksum, document.checksum)
        else:
            self.assertFalse(document.file)

    @parameterized.expand(
        [
            # Already the 26th in New Zealand: the day of the acting user, not of
            # the server.
            ("UTC", "UTC", date(2026, 3, 25)),
            ("ahead of UTC", "Pacific/Auckland", date(2026, 3, 26)),
        ]
    )
    @freeze_time("2026-03-25 22:00:00")
    def test_create_date_defaults_to_today(self, label, tz, expected):
        service = self.get_service(DocumentService, user=self.user_frodon, tz=tz)

        instances = async_to_sync(service.create)([DocumentCreateSchema(**TEXT)])

        self.assertEqual(Document.objects.get(pk=instances[0].pk).date, expected)

    def test_create_without_acting_user(self):
        # An API key acts as no user: there is no owner to default to.
        service = self.get_service(DocumentService)

        instances = async_to_sync(service.create)([DocumentCreateSchema(**TEXT)])

        self.assertIsNone(Document.objects.get(pk=instances[0].pk).user_id)

    @parameterized.expand(
        [
            # Square-bounded at 256 pixels, as WEBP; a photo turned upright.
            ("an image", "ring.png", image_bytes(size=(1000, 500)), ("WEBP", (256, 128))),
            ("a photo", "frodon.jpg", jpeg_rotated_bytes(size=(400, 200)), ("WEBP", (128, 256))),
            ("a pdf", "map.pdf", pdf_bytes(size=(600, 800)), ("WEBP", (192, 256))),
            # Nothing to draw: no thumbnail, and no error.
            ("a plain text file", "notes.txt", b"One ring", None),
        ]
    )
    def test_create_thumbnail(self, label, name, payload, expected):
        instances = async_to_sync(self.service.create)([DocumentCreateSchema(document_type=DocumentType.FILE, file=upload(name, payload))])

        document = Document.objects.get(pk=instances[0].pk)
        if expected is None:
            self.assertFalse(document.thumbnail)
        else:
            with open(document.thumbnail.storage.symlink_path(document.thumbnail.name), "rb") as stored:
                thumbnail = Image.open(stored)
                self.assertEqual((thumbnail.format, thumbnail.size), expected)
        # The file itself is stored untouched.
        self.assertEqual(document.size, len(payload))

    def test_create_thumbnail_failure_does_not_refuse_the_file(self):
        # A PDF pdfium cannot read: the document is created, with no thumbnail.
        payload = b"%PDF-1.4 not really a pdf"

        with self.assertLogs("document.thumbnails", "WARNING"):
            instances = async_to_sync(self.service.create)([DocumentCreateSchema(document_type=DocumentType.FILE, file=upload("map.pdf", payload))])

        document = Document.objects.get(pk=instances[0].pk)
        self.assertEqual((document.checksum, bool(document.thumbnail)), (hashlib.sha1(payload).hexdigest(), False))

    @parameterized.expand(
        [
            # `validate_data`, keyed by the index of the payload, before the
            # INSERT: nothing reaches the storage. Named: unnamed, the error
            # would be on `name`, raised first.
            ("a file without upload", {"name": "Map", "document_type": DocumentType.FILE}, None, 5, "file"),
            ("a file with text", {"document_type": DocumentType.FILE, "file": "map.pdf", "text_content": "<p>Here</p>"}, None, 5, "text_content"),
            ("a text with an upload", {**TEXT, "file": "map.pdf"}, None, 5, "file"),
            # The null check of `to_internal_values`, before any query.
            ("a text without name", {"document_type": DocumentType.TEXT}, None, 0, "name"),
            ("an executable upload", {"document_type": DocumentType.FILE, "file": "logo.svg"}, None, 5, "file"),
            ("an upload too large", {"document_type": DocumentType.FILE, "file": "map.pdf"}, len(PAYLOAD) - 1, 5, "file"),
        ]
    )
    def test_create_invalid(self, label, payload, max_size, query_count, error_key):
        if "file" in payload:
            payload = {**payload, "file": upload(payload["file"])}

        with patch.object(DocumentService, "MAX_UPLOAD_SIZE", max_size or DocumentService.MAX_UPLOAD_SIZE):
            with self.assertNumQueries(query_count):
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)([DocumentCreateSchema(**payload)])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Document.objects.count(), 2)
        self.assertFalse(FileReference.objects.exists())

    def test_create_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.create)([TEXT])

        self.assertEqual(Document.objects.count(), 2)

    @parameterized.expand(
        [
            # Resolved through their services, as any relation, before the
            # transaction: the roles, the owner, then the relation given.
            ("unknown contact", {"contact": "01JK0000000000000000000099"}, 3, "contact"),
            ("unknown tag", {"tags": [TAG_DRAFT_ID, TAG_UNKNOWN_ID]}, 3, "tags"),
            ("unknown owner", {"user": USER_UNKNOWN_ID}, 2, "user"),
        ]
    )
    def test_create_relations(self, label, values, query_count, error_key):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.create)([DocumentCreateSchema(**TEXT, **values)])

        self.assertEqual(list(ctx.exception.dict()[0]), [error_key])
        self.assertEqual(Document.objects.count(), 2)

    @parameterized.expand(
        [
            ("every input valid", [TEXT, {"document_type": DocumentType.FILE, "file": "map.pdf"}], 8, None),
            # All or nothing: the valid first input is not written either.
            ("the second input invalid", [TEXT, {"document_type": DocumentType.FILE, "file": "logo.svg"}], 5, {1: ["file"]}),
        ]
    )
    def test_create_batch(self, label, payloads, query_count, errors):
        data = [
            DocumentCreateSchema(**{**payload, "file": upload(payload["file"])} if "file" in payload else payload)
            for payload in payloads
        ]

        with self.assertNumQueries(query_count):
            if errors is None:
                instances = async_to_sync(self.service.create)(data)
            else:
                with self.assertRaises(ServiceValidationMultiError) as ctx:
                    async_to_sync(self.service.create)(data)

        if errors is None:
            self.assertEqual([document.name for document in instances], ["Letter to Bilbo", "map.pdf"])
            self.assertEqual(Document.objects.count(), 4)
        else:
            self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
            self.assertEqual(Document.objects.count(), 2)
            self.assertFalse(FileReference.objects.exists())

    @parameterized.expand(
        [
            ("every field", None, {"user": USER_FRODON_ID, "date": date(2026, 3, 25)}),
            ("the fields asked", ["user"], {"user": USER_FRODON_ID}),
        ]
    )
    @freeze_time("2026-03-25 10:00:00")
    def test_default_values(self, label, fields, expected):
        with self.assertNumQueries(0):
            values = async_to_sync(self.service.default_values)(fields)

        self.assertEqual(
            {name: str(value) if name == "user" else value for name, value in values.items() if value not in (None, [])},
            expected,
        )

    # ------------------------------------------
    # Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ("no filter", None, ALL_DOCUMENT_IDS),
            # The filter schema of the API, with its own lookups.
            ("a tag", DocumentFilterSchema(tag=TAG_DRAFT_ID), [DOCUMENT_NOTES_ID]),
            # Once each, though the notes carry two of them.
            ("any of several tags", DocumentFilterSchema(tag=f"{TAG_DRAFT_ID},{TAG_2026_ID},{TAG_SIGNED_ID}"), ALL_DOCUMENT_IDS),
            ("a tag category", DocumentFilterSchema(tag_category=CATEGORY_YEAR_ID), [DOCUMENT_NOTES_ID]),
            ("any of several tag categories", DocumentFilterSchema(tag_category=f"{CATEGORY_STATUS_ID},{CATEGORY_YEAR_ID}"), ALL_DOCUMENT_IDS),
            ("a contact", DocumentFilterSchema(contact=CONTACT_ELROND_ID), [DOCUMENT_NOTES_ID]),
            ("no contact", DocumentFilterSchema(contact="null"), [DOCUMENT_MINUTES_ID]),
            ("a contact without document", DocumentFilterSchema(contact=CONTACT_GALADRIEL_ID), []),
            ("the texts", DocumentFilterSchema(document_type="text"), ALL_DOCUMENT_IDS),
            ("the files", DocumentFilterSchema(document_type="file"), []),
            ("the start of a mimetype", DocumentFilterSchema(mimetype="text/"), ALL_DOCUMENT_IDS),
            ("a search term", DocumentFilterSchema(search="elrond"), [DOCUMENT_NOTES_ID]),
        ]
    )
    def test_read_filters(self, label, filters, expected_pks):
        with self.assertNumQueries(2):
            pks = list(async_to_sync(self.service.read)(filters).values_list("pk", flat=True))

        self.assertCountEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("by name", ["name"], [DOCUMENT_MINUTES_ID, DOCUMENT_NOTES_ID]),
            ("by size, descending", ["-size"], [DOCUMENT_MINUTES_ID, DOCUMENT_NOTES_ID]),
        ]
    )
    def test_read_ordering(self, label, ordering, expected_pks):
        with self.assertNumQueries(2):
            pks = [document.pk for document in async_to_sync(self.service.read)(ordering=ordering)]

        self.assertEqual(pks, expected_pks)

    @parameterized.expand(
        [
            ("plain fields", ["id", "name"], 2, {}),
            # Each relation asked is prefetched with the fields asked on it.
            ("the tags and the contact", ["id", "tags__name", "contact__display_name"], 4, {"tags": ["2026", "Draft"], "contact": "Elrond Half-elven"}),
        ]
    )
    def test_read_fields(self, label, fields, query_count, expected):
        with self.assertNumQueries(query_count):
            documents = list(async_to_sync(self.service.read)({"id": DOCUMENT_NOTES_ID}, fields=fields))
            loaded = {
                "tags": sorted(tag.name for tag in documents[0].tags.all()) if "tags" in expected else None,
                "contact": documents[0].contact.display_name if "contact" in expected else None,
            }

        self.assertEqual({name: value for name, value in loaded.items() if name in expected}, expected)
        self.assertIn("text_content", documents[0].get_deferred_fields())

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            # Only the size of a text ever moves: `DocumentQuerySet.update`.
            ("the text, and its size", DOCUMENT_NOTES_ID, {"text_content": "<p>Nine for mortal men</p>"}, 5, {"size": 26}),
            ("the contact", DOCUMENT_NOTES_ID, {"contact": CONTACT_GALADRIEL_ID}, 6, {"contact_id": CONTACT_GALADRIEL_ID}),
            ("the tags replaced", DOCUMENT_MINUTES_ID, {"tags": [TAG_DRAFT_ID]}, 9, {}),
            ("name and date", DOCUMENT_MINUTES_ID, {"name": "Minutes", "date": "2026-01-01"}, 5, {"name": "Minutes", "date": date(2026, 1, 1)}),
        ]
    )
    def test_update(self, label, pk, payload, query_count, expected_values):
        with self.assertNumQueries(query_count):
            count, queryset = async_to_sync(self.service.update)({"id": pk}, DocumentUpdateSchema(**payload))

        self.assertEqual(count, 1)
        self.assertEqual([document.pk for document in queryset], [pk])
        document = Document.objects.get(pk=pk)
        self.assertEqual({name: getattr(document, name) for name in expected_values}, expected_values)
        if "tags" in payload:
            self.assertEqual(list(document.tags.values_list("pk", flat=True)), payload["tags"])

    def test_update_metadata_of_a_file(self):
        instances = async_to_sync(self.service.create)([DocumentCreateSchema(document_type=DocumentType.FILE, file=upload())])

        async_to_sync(self.service.update)({"id": instances[0].pk}, DocumentUpdateSchema(name="Map of the Shire", tags=[TAG_SIGNED_ID]))

        document = Document.objects.get(pk=instances[0].pk)
        self.assertEqual((document.name, list(document.tags.values_list("pk", flat=True))), ("Map of the Shire", [TAG_SIGNED_ID]))
        # Untouched: the file and what is derived from it.
        self.assertEqual((document.size, document.checksum), (len(PAYLOAD), hashlib.sha1(PAYLOAD).hexdigest()))

    def test_update_partial(self):
        async_to_sync(self.service.update)({"id": DOCUMENT_NOTES_ID}, DocumentUpdateSchema(name="Notes"))

        document = Document.objects.get(pk=DOCUMENT_NOTES_ID)
        self.assertEqual(
            (document.name, document.text_content, document.size, document.contact_id),
            ("Notes", "<p>One ring</p>", 15, CONTACT_ELROND_ID),
        )

    @parameterized.expand(
        [
            # Resolved before any row is read: keyed by the index of the payload.
            ("unknown contact", DocumentUpdateSchema(contact="01JK0000000000000000000099"), 2, {0: ["contact"]}),
            ("unknown tag", DocumentUpdateSchema(tags=[TAG_UNKNOWN_ID]), 2, {0: ["tags"]}),
            # Built unvalidated, as another caller than the API could.
            ("name set to null", DocumentUpdateSchema.model_construct(name=None), 0, {0: ["name"]}),
        ]
    )
    def test_update_invalid(self, label, data, query_count, errors):
        with self.assertNumQueries(query_count):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.update)({"id": DOCUMENT_NOTES_ID}, data)

        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, errors)
        document = Document.objects.get(pk=DOCUMENT_NOTES_ID)
        self.assertEqual((document.name, document.contact_id), ("Notes of the Council of Elrond", CONTACT_ELROND_ID))

    def test_update_text_of_a_file(self):
        instances = async_to_sync(self.service.create)([DocumentCreateSchema(document_type=DocumentType.FILE, file=upload())])

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)({"id": instances[0].pk}, DocumentUpdateSchema(text_content="<p>Here be dragons</p>"))

        # `validate_data` during an update: keyed by the pk of the record.
        self.assertEqual({key: list(value) for key, value in ctx.exception.dict().items()}, {instances[0].pk: ["text_content"]})
        self.assertIsNone(Document.objects.get(pk=instances[0].pk).text_content)

    def test_update_refuses_a_dict(self):
        with self.assertNumQueries(0):
            with self.assertRaises(TypeError):
                async_to_sync(self.service.update)({"id": DOCUMENT_NOTES_ID}, {"name": "Notes"})

        self.assertEqual(Document.objects.get(pk=DOCUMENT_NOTES_ID).name, "Notes of the Council of Elrond")

    def test_update_batch(self):
        with self.assertNumQueries(6):
            count, queryset = async_to_sync(self.service.update)(
                DocumentFilterSchema(document_type="text"), DocumentUpdateSchema(contact=CONTACT_GALADRIEL_ID)
            )

        self.assertEqual(count, 2)
        self.assertCountEqual([document.pk for document in queryset], ALL_DOCUMENT_IDS)
        self.assertEqual(Document.objects.filter(contact_id=CONTACT_GALADRIEL_ID).count(), 2)

    def test_update_not_found(self):
        with self.assertNumQueries(4):
            count, queryset = async_to_sync(self.service.update)({"id": DOCUMENT_UNKNOWN_ID}, DocumentUpdateSchema(name="Red Book"))

        self.assertEqual((count, list(queryset)), (0, []))
        self.assertFalse(Document.objects.filter(name="Red Book").exists())

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a text", {"id": DOCUMENT_NOTES_ID}, 7, 1),
            ("nothing matches", {"id": DOCUMENT_UNKNOWN_ID}, 5, 0),
        ]
    )
    def test_delete(self, label, filters, query_count, affected):
        with self.assertNumQueries(query_count):
            count = async_to_sync(self.service.delete)(filters)

        self.assertEqual(count, affected)
        self.assertEqual(Document.objects.count(), 2 - affected)

    @parameterized.expand(
        [
            # The file and its thumbnail leave the storage with the row.
            ("a file with a thumbnail", "ring.png", image_bytes(), True),
            ("a file without thumbnail", "notes.txt", b"One ring", False),
        ]
    )
    def test_delete_removes_the_files(self, label, name, payload, has_thumbnail):
        instances = async_to_sync(self.service.create)([DocumentCreateSchema(document_type=DocumentType.FILE, file=upload(name, payload))])
        document = Document.objects.get(pk=instances[0].pk)
        stored = [document.file] + ([document.thumbnail] if has_thumbnail else [])
        self.assertTrue(all(field.storage.symlink_exists(field.name) for field in stored))

        async_to_sync(self.service.delete)({"id": document.pk})

        self.assertFalse(Document.objects.filter(pk=document.pk).exists())
        # `symlink_exists`, not `exists`: the storage files by checksum.
        self.assertFalse(any(field.storage.symlink_exists(field.name) for field in stored))
        self.assertFalse(FileReference.objects.exists())
