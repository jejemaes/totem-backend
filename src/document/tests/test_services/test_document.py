import hashlib
import json
from unittest.mock import patch

from asgiref.sync import async_to_sync
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized
from PIL import Image

from base.models import FileReference
from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from document.choices import DocumentType
from document.models import Document
from document.schemas import DocumentCreateSchema, DocumentFilterSchema, DocumentUpdateSchema
from document.services import DocumentService
from document.tests.common import (
    CATEGORY_STATUS_ID,
    CONTACT_ELROND_ID,
    CONTACT_GALADRIEL_ID,
    CATEGORY_YEAR_ID,
    DOCUMENT_MINUTES_ID,
    DOCUMENT_NOTES_ID,
    ROLES_FIXTURE,
    TAG_2026_ID,
    TAG_DRAFT_ID,
    TAG_SIGNED_ID,
    USER_ID1,
    DocumentTestMixin,
)
from document.tests.images import image_bytes, jpeg_rotated_bytes, pdf_bytes
from user.access_rights import get_all_permission

# A real one, small: a creation now makes a thumbnail of it.
PAYLOAD = pdf_bytes(size=(60, 80))


def upload(name="map.pdf", payload=PAYLOAD):
    return SimpleUploadedFile(name, payload, content_type="application/octet-stream")


class TestDocumentService(DocumentTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.env = Environment(user=self.user, language="en-us")
        self.service = self.env.get(DocumentService)

    def create(self, **payload):
        return async_to_sync(self.service.create)([DocumentCreateSchema(**payload)])[0]

    def assertNothingWritten(self, document_count):
        """No row, and no file: `FileField.pre_save` commits the file with the
        INSERT, and each stored file leaves a `FileReference` behind."""
        self.assertEqual(Document.objects.count(), document_count)
        self.assertFalse(FileReference.objects.exists())

    # ------------------------------------------
    # Tests Input Contract
    # ------------------------------------------

    def test_update_schema_has_neither_type_nor_file(self):
        # Replacing a file means creating a new document.
        self.assertNotIn("document_type", DocumentUpdateSchema.model_fields)
        self.assertNotIn("file", DocumentUpdateSchema.model_fields)

    @parameterized.expand([("mimetype",), ("checksum",), ("size",)])
    def test_derived_field_is_on_no_write_schema(self, field):
        self.assertNotIn(field, DocumentCreateSchema.model_fields)
        self.assertNotIn(field, DocumentUpdateSchema.model_fields)

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_file_derives_its_values(self):
        document = self.create(document_type=DocumentType.FILE, file=upload())

        document = Document.objects.get(pk=document.pk)
        self.assertEqual(document.name, "map.pdf")
        self.assertEqual(document.mimetype, "application/pdf")
        self.assertEqual(document.checksum, hashlib.sha1(PAYLOAD).hexdigest())
        self.assertEqual(document.size, len(PAYLOAD))
        self.assertIsNone(document.text_content)
        # The storage filed the uploaded bytes, not the empty rest of a stream
        # left at EOF: it was rewound after being read for the checksum.
        self.assertEqual(
            FileReference.objects.get(symbolic_path=document.file.name).checksum,
            document.checksum,
        )

    def test_create_file_keeps_the_name_given(self):
        document = self.create(name="Map of the Shire", document_type=DocumentType.FILE, file=upload())
        self.assertEqual(Document.objects.get(pk=document.pk).name, "Map of the Shire")

    def test_create_file_with_relations(self):
        document = self.create(
            document_type=DocumentType.FILE,
            file=upload(),
            date="2026-03-25",
            user=USER_ID1,
            contact=CONTACT_GALADRIEL_ID,
            tags=[TAG_DRAFT_ID, TAG_2026_ID],
        )
        document = Document.objects.get(pk=document.pk)
        self.assertEqual(str(document.date), "2026-03-25")
        self.assertEqual(str(document.user_id), USER_ID1)
        self.assertEqual(document.contact_id, CONTACT_GALADRIEL_ID)
        self.assertEqual(set(document.tags.values_list("id", flat=True)), {TAG_DRAFT_ID, TAG_2026_ID})

    def test_create_defaults_to_the_acting_user(self):
        document = self.create(name="Letter to Bilbo", document_type=DocumentType.TEXT)
        self.assertEqual(str(Document.objects.get(pk=document.pk).user_id), str(self.user.pk))
        # Announced as it is applied.
        self.assertEqual(async_to_sync(self.service.default_values)(["user"]), {"user": self.user.pk})

    @parameterized.expand(
        [
            ("UTC", "2026-03-25"),
            # Already the 26th in New Zealand: the day of the acting user, not of the server.
            ("Pacific/Auckland", "2026-03-26"),
        ]
    )
    @freeze_time("2026-03-25 22:00:00")
    def test_create_defaults_to_today(self, tz, expected):
        service = self.env(tz=tz).get(DocumentService)
        document = async_to_sync(service.create)(
            [DocumentCreateSchema(name="Letter to Bilbo", document_type=DocumentType.TEXT)]
        )[0]
        self.assertEqual(str(Document.objects.get(pk=document.pk).date), expected)

    def test_create_keeps_a_date_set_to_null(self):
        document = self.create(name="Letter to Bilbo", document_type=DocumentType.TEXT, date=None)
        self.assertIsNone(Document.objects.get(pk=document.pk).date)

    def test_create_keeps_a_user_set_to_null(self):
        document = self.create(name="Letter to Bilbo", document_type=DocumentType.TEXT, user=None)
        self.assertIsNone(Document.objects.get(pk=document.pk).user_id)

    def test_create_without_acting_user_has_no_default_user(self):
        # An API key acts as no user.
        service = Environment(user=None, language="en-us").get(DocumentService)
        document = async_to_sync(service.create)(
            [DocumentCreateSchema(name="Letter to Bilbo", document_type=DocumentType.TEXT)]
        )[0]
        self.assertIsNone(Document.objects.get(pk=document.pk).user_id)

    def test_create_text_derives_its_values(self):
        document = self.create(
            name="Letter to Bilbo", document_type=DocumentType.TEXT, text_content="<p>Élessar</p>"
        )

        document = Document.objects.get(pk=document.pk)
        self.assertEqual(document.mimetype, "text/html")
        # In bytes: two for "é" in UTF-8.
        self.assertEqual(document.size, 15)
        self.assertIsNone(document.checksum)
        self.assertFalse(document.file)

    def test_create_empty_text(self):
        document = self.create(name="Blank page", document_type=DocumentType.TEXT)
        self.assertEqual(Document.objects.get(pk=document.pk).size, 0)

    @parameterized.expand(
        [
            # Named: unnamed, the error would be on `name`, raised first.
            ("file without upload", {"name": "Map", "document_type": DocumentType.FILE}, "file"),
            (
                "file with text",
                {"document_type": DocumentType.FILE, "file": "map.pdf", "text_content": "<p>Here</p>"},
                "text_content",
            ),
            ("text with upload", {"name": "Letter", "document_type": DocumentType.TEXT, "file": "map.pdf"}, "file"),
            ("text without name", {"document_type": DocumentType.TEXT}, "name"),
            ("executable upload", {"document_type": DocumentType.FILE, "file": "logo.svg"}, "file"),
            # Resolved through its service, as any relation.
            (
                "unknown contact",
                {"name": "Letter", "document_type": DocumentType.TEXT, "contact": "01JK0000000000000000000099"},
                "contact",
            ),
        ]
    )
    def test_create_invalid(self, dummy, payload, field):
        if "file" in payload:
            payload = {**payload, "file": upload(payload["file"])}
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self.create(**payload)
        self.assertEqual(list(ctx.exception.dict()[0]), [field])
        self.assertNothingWritten(2)

    def test_create_too_large(self):
        with patch.object(DocumentService, "MAX_UPLOAD_SIZE", len(PAYLOAD) - 1):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                self.create(document_type=DocumentType.FILE, file=upload())
        self.assertEqual(list(ctx.exception.dict()[0]), ["file"])
        self.assertNothingWritten(2)

    # ------------------------------------------
    # Tests Thumbnail
    # ------------------------------------------

    @parameterized.expand(
        [
            ("image", "ring.png", image_bytes(size=(1000, 500)), (256, 128)),
            ("photo", "frodon.jpg", jpeg_rotated_bytes(size=(400, 200)), (128, 256)),
            ("pdf", "map.pdf", pdf_bytes(size=(600, 800)), (192, 256)),
        ]
    )
    def test_create_file_with_thumbnail(self, dummy, name, payload, size):
        document = self.create(document_type=DocumentType.FILE, file=upload(name, payload))

        document = Document.objects.get(pk=document.pk)
        with open(document.thumbnail.storage.symlink_path(document.thumbnail.name), "rb") as stored:
            thumbnail = Image.open(stored)
            self.assertEqual((thumbnail.format, thumbnail.size), ("WEBP", size))
        # The file itself is stored untouched.
        self.assertEqual(document.size, len(payload))

    def test_create_file_without_thumbnail(self):
        document = self.create(document_type=DocumentType.FILE, file=upload("notes.txt", b"One ring"))
        self.assertFalse(Document.objects.get(pk=document.pk).thumbnail)

    def test_create_text_without_thumbnail(self):
        document = self.create(name="Letter", document_type=DocumentType.TEXT, text_content="<p>Hi</p>")
        self.assertFalse(Document.objects.get(pk=document.pk).thumbnail)

    def test_thumbnail_failure_does_not_refuse_the_upload(self):
        # A PDF pdfium cannot read: the document is created, with no thumbnail.
        payload = b"%PDF-1.4 not really a pdf"
        with self.assertLogs("document.thumbnails", "WARNING"):
            documents = async_to_sync(self.service.upload)([upload("map.pdf", payload)])
        document = Document.objects.get(pk=documents[0].pk)
        self.assertEqual(document.checksum, hashlib.sha1(payload).hexdigest())
        self.assertFalse(document.thumbnail)

    def test_delete_removes_the_thumbnail(self):
        document = self.create(document_type=DocumentType.FILE, file=upload("ring.png", image_bytes()))
        thumbnail = Document.objects.get(pk=document.pk).thumbnail
        self.assertTrue(thumbnail.storage.symlink_exists(thumbnail.name))

        async_to_sync(self.service.delete)({"id": document.pk})

        self.assertFalse(thumbnail.storage.symlink_exists(thumbnail.name))
        self.assertFalse(FileReference.objects.exists())

    # ------------------------------------------
    # Tests Upload
    # ------------------------------------------

    def test_upload_creates_one_document_per_file(self):
        documents = async_to_sync(self.service.upload)(
            [upload("map.pdf"), upload("ring.png", image_bytes())],
            tags=[TAG_SIGNED_ID],
            user=USER_ID1,
            contact=CONTACT_GALADRIEL_ID,
        )

        documents = Document.objects.filter(pk__in=[d.pk for d in documents]).order_by("name")
        self.assertEqual(
            [(d.name, d.document_type, d.mimetype) for d in documents],
            [("map.pdf", "file", "application/pdf"), ("ring.png", "file", "image/png")],
        )
        for document in documents:
            self.assertEqual(str(document.user_id), USER_ID1)
            self.assertEqual(document.contact_id, CONTACT_GALADRIEL_ID)
            self.assertEqual(list(document.tags.values_list("id", flat=True)), [TAG_SIGNED_ID])

    def test_upload_without_common_values(self):
        documents = async_to_sync(self.service.upload)([upload()])
        document = Document.objects.get(pk=documents[0].pk)
        # The acting user, as for `create`: see `test_create_defaults_to_the_acting_user`.
        self.assertEqual(str(document.user_id), str(self.user.pk))
        self.assertIsNone(document.contact_id)
        self.assertFalse(document.tags.exists())

    def test_upload_is_all_or_nothing(self):
        # The second file is refused: none is created, and the error says which.
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.upload)(
                [upload("map.pdf"), upload("logo.svg"), upload("ring.png")]
            )
        self.assertEqual(list(ctx.exception.dict()), [1])
        self.assertEqual(list(ctx.exception.dict()[1]), ["file"])
        self.assertNothingWritten(2)

    def test_upload_too_many_files(self):
        with patch.object(DocumentService, "MAX_UPLOAD_COUNT", 2):
            with self.assertRaises(ServiceValidationMultiError) as ctx:
                async_to_sync(self.service.upload)([upload(), upload(), upload()])
        self.assertEqual(list(ctx.exception.dict()), ["files"])
        self.assertNothingWritten(2)

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"tag": TAG_DRAFT_ID}, [DOCUMENT_NOTES_ID]),
            # Once each, though the notes carry both tags.
            ({"tag": f"{TAG_DRAFT_ID},{TAG_2026_ID},{TAG_SIGNED_ID}"}, [DOCUMENT_NOTES_ID, DOCUMENT_MINUTES_ID]),
            ({"tag_category": CATEGORY_YEAR_ID}, [DOCUMENT_NOTES_ID]),
            # Once each, though the notes carry two tags of Status and Year.
            ({"tag_category": f"{CATEGORY_STATUS_ID},{CATEGORY_YEAR_ID}"}, [DOCUMENT_NOTES_ID, DOCUMENT_MINUTES_ID]),
            ({"contact": CONTACT_ELROND_ID}, [DOCUMENT_NOTES_ID]),
            ({"contact": "null"}, [DOCUMENT_MINUTES_ID]),
            ({"contact": CONTACT_GALADRIEL_ID}, []),
            ({"document_type": "text"}, [DOCUMENT_NOTES_ID, DOCUMENT_MINUTES_ID]),
            ({"document_type": "file"}, []),
            ({"mimetype": "text/"}, [DOCUMENT_NOTES_ID, DOCUMENT_MINUTES_ID]),
            ({"mimetype": "image/"}, []),
            ({"search": "elrond"}, [DOCUMENT_NOTES_ID]),
        ]
    )
    def test_read_filters(self, filters, expected_ids):
        queryset = async_to_sync(self.service.read)(DocumentFilterSchema(**filters))
        self.assertEqual(sorted(queryset.values_list("id", flat=True)), sorted(expected_ids))

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_update_text_follows_the_size(self):
        async_to_sync(self.service.update)(
            {"id": DOCUMENT_NOTES_ID}, DocumentUpdateSchema(text_content="<p>Nine for mortal men</p>")
        )
        self.assertEqual(Document.objects.get(pk=DOCUMENT_NOTES_ID).size, 26)

    def test_update_contact(self):
        async_to_sync(self.service.update)(
            {"id": DOCUMENT_NOTES_ID}, DocumentUpdateSchema(contact=CONTACT_GALADRIEL_ID)
        )
        self.assertEqual(Document.objects.get(pk=DOCUMENT_NOTES_ID).contact_id, CONTACT_GALADRIEL_ID)

    def test_update_metadata_of_a_file(self):
        document = self.create(document_type=DocumentType.FILE, file=upload())
        async_to_sync(self.service.update)(
            {"id": document.pk}, DocumentUpdateSchema(name="Map of the Shire", tags=[TAG_SIGNED_ID])
        )
        document = Document.objects.get(pk=document.pk)
        self.assertEqual(document.name, "Map of the Shire")
        self.assertEqual(list(document.tags.values_list("id", flat=True)), [TAG_SIGNED_ID])
        # Untouched: the file and what is derived from it.
        self.assertEqual(document.size, len(PAYLOAD))

    def test_update_text_of_a_file_is_refused(self):
        document = self.create(document_type=DocumentType.FILE, file=upload())
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": document.pk}, DocumentUpdateSchema(text_content="<p>Here be dragons</p>")
            )
        # Keyed by the record: `validate_data` on an update.
        self.assertEqual(list(ctx.exception.dict()[document.pk]), ["text_content"])
        self.assertIsNone(Document.objects.get(pk=document.pk).text_content)

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete_removes_the_file(self):
        document = self.create(document_type=DocumentType.FILE, file=upload())
        storage, name = document.file.storage, Document.objects.get(pk=document.pk).file.name
        # `symlink_exists`, not `exists`: the storage stores by checksum, and
        # `exists` looks under the filestore -- see `TestMediaService`.
        self.assertTrue(storage.symlink_exists(name))

        async_to_sync(self.service.delete)({"id": document.pk})

        self.assertFalse(Document.objects.filter(pk=document.pk).exists())
        self.assertFalse(storage.symlink_exists(name))
        self.assertFalse(FileReference.objects.exists())


class TestDocumentRoles(TestCase):
    """The roles shipped. No rule is registered for the documents, so the roles
    differ by their scopes alone, which the controllers check."""

    def roles(self):
        return {
            item["pk"]: set(json.loads(item["fields"]["permissions"]))
            for item in json.loads(ROLES_FIXTURE.read_text())
        }

    def test_every_scope_granted_is_registered(self):
        registered = {permission for permission, _ in get_all_permission()}
        for pk, permissions in self.roles().items():
            self.assertLessEqual(permissions, registered, pk)

    def test_user_reads_the_tags_and_manages_the_documents(self):
        self.assertEqual(
            self.roles()["DOCUMENT_USER"],
            {
                "totem.document.create",
                "totem.document.read",
                "totem.document.update",
                "totem.document.delete",
                "totem.documenttag.read",
                "totem.documenttagcategory.read",
            },
        )

    def test_manager_manages_everything(self):
        self.assertEqual(
            self.roles()["DOCUMENT_MANAGER"],
            {
                f"totem.{model}.{operation}"
                for model in ("document", "documenttag", "documenttagcategory")
                for operation in ("create", "read", "update", "delete")
            },
        )
