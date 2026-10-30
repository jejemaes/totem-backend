from datetime import date

from base.models import Country
from contact.models import Contact, ContactTag
from user.tests.test_api.common import CommonTestMixin as UserCommonTestMixin

CONTACT_ID1 = "01JK0000000000000000000001"
CONTACT_ID2 = "01JK0000000000000000000002"
CONTACT_ID3 = "01JK0000000000000000000003"

TAG_ID1 = "01JT0000000000000000000001"
TAG_ID2 = "01JT0000000000000000000002"
TAG_ID3 = "01JT0000000000000000000003"

CONTACT_SCOPES = ["totem.contact.create", "totem.contact.read", "totem.contact.update", "totem.contact.delete"]
TAG_SCOPES = [
    "totem.contacttag.create",
    "totem.contacttag.read",
    "totem.contacttag.update",
    "totem.contacttag.delete",
]

PERMISSION_DENIED = {"detail": ["You do not have permission to perform this action."]}


class CommonTestMixin(UserCommonTestMixin):
    """ The address book every API test of `contact` reads. Data only.

    On top of the users, `role` and API key of `user`:

        Tags: Fellowship (color 3), Hobbit (5), Wizard (9, on nobody)

        CONTACT_ID1  Sam Gamegie     sam@lacomte.com       Hobbiton, The Shire   [Fellowship, Hobbit]
        CONTACT_ID2  Aragorn Elessar aragorn@gondor.com    Minas Tirith, Gondor  [Fellowship]
        CONTACT_ID3  Bilbon Sacquet  (no email, no address, born 2890-09-22)     no tag

    No access rule is registered on either model: whoever holds a scope reaches
    every contact and every tag. `role` is granted nothing here: each test class
    grants the scopes of its resource.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.country_shire, cls.country_gondor = Country.objects.bulk_create([
            Country(code="SH", name="The Shire"),
            Country(code="GD", name="Gondor"),
        ])

        cls.tag_fellowship, cls.tag_hobbit, cls.tag_wizard = ContactTag.objects.bulk_create([
            ContactTag(id=TAG_ID1, name="Fellowship", color=3),
            ContactTag(id=TAG_ID2, name="Hobbit", color=5),
            ContactTag(id=TAG_ID3, name="Wizard", color=9),
        ])

        cls.contact_sam, cls.contact_aragorn, cls.contact_bilbon = Contact.objects.bulk_create([
            Contact(
                id=CONTACT_ID1, first_name="Sam", last_name="Gamegie", email="sam@lacomte.com",
                mobile="+32 470 00 00 01", street="Bagshot Row", number="3", zip="1000",
                city="Hobbiton", country=cls.country_shire,
            ),
            Contact(
                id=CONTACT_ID2, first_name="Aragorn", last_name="Elessar", email="aragorn@gondor.com",
                street="The Citadel", zip="7000", city="Minas Tirith", country=cls.country_gondor,
            ),
            Contact(
                id=CONTACT_ID3, first_name="Bilbon", last_name="Sacquet", birth_date=date(2890, 9, 22),
            ),
        ])
        Contact.tags.through.objects.bulk_create([
            Contact.tags.through(contact_id=CONTACT_ID1, contacttag_id=TAG_ID1),
            Contact.tags.through(contact_id=CONTACT_ID1, contacttag_id=TAG_ID2),
            Contact.tags.through(contact_id=CONTACT_ID2, contacttag_id=TAG_ID1),
        ])
