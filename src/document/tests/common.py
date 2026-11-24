from contact.models import Contact
from core.testing import MediaRootTestMixin
from document.choices import DocumentType
from document.models import Document, DocumentTag, DocumentTagCategory
from user.models import User

USER_ID1 = "14041cce-8719-4637-92b1-51c4ade4b643"

CATEGORY_STATUS_ID = "01JD0000000000000000000001"
CATEGORY_YEAR_ID = "01JD0000000000000000000002"
CATEGORY_EMPTY_ID = "01JD0000000000000000000003"

TAG_DRAFT_ID = "01JT0000000000000000000001"
TAG_SIGNED_ID = "01JT0000000000000000000002"
TAG_2026_ID = "01JT0000000000000000000003"

CONTACT_ELROND_ID = "01JK0000000000000000000001"
CONTACT_GALADRIEL_ID = "01JK0000000000000000000002"

DOCUMENT_NOTES_ID = "01JX0000000000000000000001"
DOCUMENT_MINUTES_ID = "01JX0000000000000000000002"


class DocumentTestMixin(MediaRootTestMixin):
    """The data of the model tests; the service tests have their own, in
    `test_services/common_*`.

    Two tag categories, Status (Draft, Signed) and Year (2026), and a third
    one with no tag; two contacts, Elrond and Galadriel; two text documents,
    the notes tagged Draft and 2026 and filed under Elrond, the minutes Signed
    and under no contact. No file document: a file is derived by the service,
    so the tests that need one create it there.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = User.objects.create(
            pk=USER_ID1,
            username="Frodon",
            password="MiL0u4ev3r",
            email="frodon@shire.me",
        )
        cls.contact_elrond, cls.contact_galadriel = Contact.objects.bulk_create([
            Contact(id=CONTACT_ELROND_ID, first_name="Elrond", last_name="Half-elven"),
            Contact(id=CONTACT_GALADRIEL_ID, first_name="Galadriel", last_name="of Lothlórien"),
        ])
        cls.category_status, cls.category_year, cls.category_empty = DocumentTagCategory.objects.bulk_create([
            DocumentTagCategory(id=CATEGORY_STATUS_ID, name="Status", sequence=1, color=3),
            DocumentTagCategory(id=CATEGORY_YEAR_ID, name="Year", sequence=2),
            DocumentTagCategory(id=CATEGORY_EMPTY_ID, name="Kingdom", sequence=3),
        ])
        cls.tag_draft, cls.tag_signed, cls.tag_2026 = DocumentTag.objects.bulk_create([
            DocumentTag(id=TAG_DRAFT_ID, name="Draft", category=cls.category_status, sequence=1),
            DocumentTag(id=TAG_SIGNED_ID, name="Signed", category=cls.category_status, sequence=2),
            DocumentTag(id=TAG_2026_ID, name="2026", category=cls.category_year),
        ])
        cls.document_notes, cls.document_minutes = Document.objects.bulk_create([
            Document(
                id=DOCUMENT_NOTES_ID,
                name="Notes of the Council of Elrond",
                document_type=DocumentType.TEXT,
                text_content="<p>One ring</p>",
                mimetype="text/html",
                size=15,
                contact=cls.contact_elrond,
            ),
            Document(
                id=DOCUMENT_MINUTES_ID,
                name="Minutes of the Fellowship of the Ring",
                document_type=DocumentType.TEXT,
                text_content="<p>Nine walkers</p>",
                mimetype="text/html",
                size=18,
            ),
        ])
        cls.document_notes.tags.set([cls.tag_draft, cls.tag_2026])
        cls.document_minutes.tags.set([cls.tag_signed])
