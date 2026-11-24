from contact.models import Contact
from core.testing import MediaRootTestMixin
from document.choices import DocumentType
from document.models import Document, DocumentTag, DocumentTagCategory
from user.tests.test_api.common import CommonTestMixin as UserCommonTestMixin

CATEGORY_STATUS_ID = "01JD0000000000000000000001"
CATEGORY_REALM_ID = "01JD0000000000000000000002"
CATEGORY_EMPTY_ID = "01JD0000000000000000000003"

TAG_DRAFT_ID = "01JT0000000000000000000001"
TAG_SIGNED_ID = "01JT0000000000000000000002"
TAG_SHIRE_ID = "01JT0000000000000000000003"

CONTACT_ELROND_ID = "01JK0000000000000000000001"
CONTACT_GALADRIEL_ID = "01JK0000000000000000000002"

DOCUMENT_NOTES_ID = "01JX0000000000000000000001"
DOCUMENT_MINUTES_ID = "01JX0000000000000000000002"

DOCUMENT_SCOPES = ["totem.document.create", "totem.document.read", "totem.document.update", "totem.document.delete"]
TAG_SCOPES = ["totem.documenttag.create", "totem.documenttag.read", "totem.documenttag.update", "totem.documenttag.delete"]
CATEGORY_SCOPES = [
    "totem.documenttagcategory.create",
    "totem.documenttagcategory.read",
    "totem.documenttagcategory.update",
    "totem.documenttagcategory.delete",
]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class CommonTestMixin(MediaRootTestMixin, UserCommonTestMixin):
    """ The tags and documents every API test of `document` reads. Data only.

    On top of the users, `role` and API key of `user`:

        Status (sequence 1, color 3)   Draft (1), Signed (2)
        Realm  (sequence 2)            The Shire
        Kingdom (sequence 3)           no tag

    Contacts Elrond and Galadriel. Two text documents: the notes of the Council,
    tagged Draft and The Shire, filed under Elrond, in charge of Frodon; the
    minutes of the Fellowship, Signed, under no contact and no one. No file
    document: its derived values come from the service, so the tests needing
    one create it through the API.

    `role` is granted nothing here: each test class grants the scopes of its
    resource. A fresh `MEDIA_ROOT` per class keeps the uploads out of the real one.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.contact_elrond, cls.contact_galadriel = Contact.objects.bulk_create([
            Contact(id=CONTACT_ELROND_ID, first_name="Elrond", last_name="Half-elven"),
            Contact(id=CONTACT_GALADRIEL_ID, first_name="Galadriel", last_name="of Lothlórien"),
        ])
        cls.category_status, cls.category_realm, cls.category_empty = DocumentTagCategory.objects.bulk_create([
            DocumentTagCategory(id=CATEGORY_STATUS_ID, name="Status", sequence=1, color=3),
            DocumentTagCategory(id=CATEGORY_REALM_ID, name="Realm", sequence=2),
            DocumentTagCategory(id=CATEGORY_EMPTY_ID, name="Kingdom", sequence=3),
        ])
        cls.tag_draft, cls.tag_signed, cls.tag_shire = DocumentTag.objects.bulk_create([
            DocumentTag(id=TAG_DRAFT_ID, name="Draft", category=cls.category_status, sequence=1),
            DocumentTag(id=TAG_SIGNED_ID, name="Signed", category=cls.category_status, sequence=2),
            DocumentTag(id=TAG_SHIRE_ID, name="The Shire", category=cls.category_realm),
        ])
        cls.document_notes, cls.document_minutes = Document.objects.bulk_create([
            Document(
                id=DOCUMENT_NOTES_ID,
                name="Notes of the Council of Elrond",
                document_type=DocumentType.TEXT,
                text_content="<p>One ring</p>",
                mimetype="text/html",
                size=15,
                user=cls.user_frodon,
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
        cls.document_notes.tags.set([cls.tag_draft, cls.tag_shire])
        cls.document_minutes.tags.set([cls.tag_signed])
