from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from document.choices import DocumentType
from document.models import Document
from document.tests.common import DOCUMENT_NOTES_ID, DocumentTestMixin


class TestDocumentModel(DocumentTestMixin, TestCase):

    # ------------------------------------------
    # Type and content
    # ------------------------------------------

    def test_text_without_file_stores_an_empty_string(self):
        """Not NULL: `FileField.get_prep_value` stores a missing file as `''`.
        The constraint reads both, see `NO_FILE`."""
        self.assertEqual(
            Document.objects.filter(pk=DOCUMENT_NOTES_ID).values_list("file", flat=True).get(), ""
        )

    def test_file_document_with_its_file(self):
        document = Document.objects.create(
            name="Map", document_type=DocumentType.FILE, file=ContentFile(b"%PDF", name="map.pdf")
        )
        self.assertTrue(document.file.name)

    def test_file_document_without_file_is_refused(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.create(name="Map", document_type=DocumentType.FILE)

    def test_file_document_with_text_is_refused(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.create(
                name="Map",
                document_type=DocumentType.FILE,
                file=ContentFile(b"%PDF", name="map.pdf"),
                text_content="<p>Here be dragons</p>",
            )

    def test_text_document_with_file_is_refused(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Document.objects.create(
                name="Map", document_type=DocumentType.TEXT, file=ContentFile(b"%PDF", name="map.pdf")
            )

    # ------------------------------------------
    # QuerySet update
    # ------------------------------------------

    def test_update_stamps_the_update_date(self):
        before = timezone.now() - timedelta(seconds=1)
        Document.objects.filter(pk=DOCUMENT_NOTES_ID).update(name="Notes")
        self.assertGreater(Document.objects.get(pk=DOCUMENT_NOTES_ID).update_date, before)

    def test_update_of_the_text_follows_the_size(self):
        # Two bytes for "é" in UTF-8.
        Document.objects.filter(pk=DOCUMENT_NOTES_ID).update(text_content="<p>Élessar</p>")
        self.assertEqual(Document.objects.get(pk=DOCUMENT_NOTES_ID).size, 15)

    def test_update_of_the_text_to_none_empties_the_size(self):
        Document.objects.filter(pk=DOCUMENT_NOTES_ID).update(text_content=None)
        self.assertEqual(Document.objects.get(pk=DOCUMENT_NOTES_ID).size, 0)

    def test_update_without_the_text_keeps_the_size(self):
        Document.objects.filter(pk=DOCUMENT_NOTES_ID).update(name="Notes")
        self.assertEqual(Document.objects.get(pk=DOCUMENT_NOTES_ID).size, 15)

    # ------------------------------------------
    # Contact
    # ------------------------------------------

    def test_document_outlives_its_contact(self):
        self.contact_elrond.delete()
        self.assertIsNone(Document.objects.get(pk=DOCUMENT_NOTES_ID).contact_id)

    # ------------------------------------------
    # File cleanup
    # ------------------------------------------

    def test_file_is_deleted_with_the_document(self):
        document = Document.objects.create(
            name="Map", document_type=DocumentType.FILE, file=ContentFile(b"%PDF", name="map.pdf")
        )
        storage, name = document.file.storage, document.file.name
        # `symlink_exists`, not `exists`: see `TestMediaService`.
        self.assertTrue(storage.symlink_exists(name))

        Document.objects.filter(pk=document.pk).delete()

        self.assertFalse(storage.symlink_exists(name))
