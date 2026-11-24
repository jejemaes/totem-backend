from django.core.files.uploadedfile import SimpleUploadedFile

from contact.models import Contact
from core.testing import MediaRootTestMixin
from document.choices import DocumentType
from document.models import Document
from document.tests.images import pdf_bytes

from document.tests.test_services.common_document_tag import DocumentTagServiceCommonMixin

CONTACT_ELROND_ID = "01JK0000000000000000000001"
CONTACT_GALADRIEL_ID = "01JK0000000000000000000002"

DOCUMENT_NOTES_ID = "01JX0000000000000000000001"
DOCUMENT_MINUTES_ID = "01JX0000000000000000000002"

DOCUMENT_UNKNOWN_ID = "01JX0000000000000000000099"

# A real one, small: a creation makes a thumbnail of it.
PAYLOAD = pdf_bytes(size=(60, 80))


def upload(name="map.pdf", payload=PAYLOAD):
    return SimpleUploadedFile(name, payload, content_type="application/octet-stream")


class DocumentServiceCommonMixin(MediaRootTestMixin, DocumentTagServiceCommonMixin):
    """ On top of the tags, two contacts, Elrond and Galadriel, and two text
    documents:

        Notes of the Council of Elrond         [Draft, 2026]  <Elrond>
        Minutes of the Fellowship of the Ring  [Signed]       no contact

    No file document: a file is derived by the service, so a test needing one
    uploads it, in the temporary `MEDIA_ROOT`. Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.contact_elrond, cls.contact_galadriel = Contact.objects.bulk_create([
            Contact(id=CONTACT_ELROND_ID, first_name="Elrond", last_name="Half-elven"),
            Contact(id=CONTACT_GALADRIEL_ID, first_name="Galadriel", last_name="of Lothlórien"),
        ])
        cls.document_notes, cls.document_minutes = Document.objects.bulk_create([
            Document(
                id=DOCUMENT_NOTES_ID, name="Notes of the Council of Elrond", document_type=DocumentType.TEXT,
                text_content="<p>One ring</p>", mimetype="text/html", size=15, contact=cls.contact_elrond,
            ),
            Document(
                id=DOCUMENT_MINUTES_ID, name="Minutes of the Fellowship of the Ring", document_type=DocumentType.TEXT,
                text_content="<p>Nine walkers</p>", mimetype="text/html", size=18,
            ),
        ])
        cls.document_notes.tags.set([cls.tag_draft, cls.tag_2026])
        cls.document_minutes.tags.set([cls.tag_signed])
