from datetime import date

from base.models import Country
from contact.models import Contact

from contact.tests.test_services.common_contact_tag import (
    TAG_FELLOWSHIP_ID,
    TAG_HOBBIT_ID,
    ContactTagServiceCommonMixin,
)

CONTACT_PONY_ID = "01JK0000000000000000000001"
CONTACT_SAM_ID = "01JK0000000000000000000002"
CONTACT_ARAGORN_ID = "01JK0000000000000000000003"
CONTACT_BILBON_ID = "01JK0000000000000000000004"
CONTACT_GREEN_DRAGON_ID = "01JK0000000000000000000005"

CONTACT_UNKNOWN_ID = "01JK0000000000000000000099"


class ContactServiceCommonMixin(ContactTagServiceCommonMixin):
    """ The address book, on top of the tags:

        The Prancing Pony  company, VAT BE0123456789, Bree, no tag
         |- Sam Gamegie    sam@lacomte.com, Hobbiton, The Shire  [Fellowship, Hobbit]
        Aragorn Elessar    aragorn@gondor.com, Minas Tirith, Gondor  [Fellowship]
        Bilbon Sacquet     born 2890-09-22, no email, no address, no tag
        The Green Dragon   company, no VAT, no contact, no tag

    Countries: The Shire (SH) and Gondor (GD). Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.country_shire, cls.country_gondor = Country.objects.bulk_create([
            Country(code="SH", name="The Shire"),
            Country(code="GD", name="Gondor"),
        ])
        # The company first: Sam points at it.
        cls.contact_pony, cls.contact_sam, cls.contact_aragorn, cls.contact_bilbon, cls.contact_green_dragon = (
            Contact.objects.bulk_create([
                Contact(
                    id=CONTACT_PONY_ID, is_company=True, name="The Prancing Pony", vat="BE0123456789",
                    email="barliman@prancingpony.com", city="Bree",
                ),
                Contact(
                    id=CONTACT_SAM_ID, first_name="Sam", last_name="Gamegie", email="sam@lacomte.com",
                    street="Bagshot Row", number="3", city="Hobbiton", country=cls.country_shire,
                    parent_id=CONTACT_PONY_ID,
                ),
                Contact(
                    id=CONTACT_ARAGORN_ID, first_name="Aragorn", last_name="Elessar", email="aragorn@gondor.com",
                    city="Minas Tirith", country=cls.country_gondor,
                ),
                Contact(id=CONTACT_BILBON_ID, first_name="Bilbon", last_name="Sacquet", birth_date=date(2890, 9, 22)),
                Contact(id=CONTACT_GREEN_DRAGON_ID, is_company=True, name="The Green Dragon", city="Bywater"),
            ])
        )
        Contact.tags.through.objects.bulk_create([
            Contact.tags.through(contact_id=CONTACT_SAM_ID, contacttag_id=TAG_FELLOWSHIP_ID),
            Contact.tags.through(contact_id=CONTACT_SAM_ID, contacttag_id=TAG_HOBBIT_ID),
            Contact.tags.through(contact_id=CONTACT_ARAGORN_ID, contacttag_id=TAG_FELLOWSHIP_ID),
        ])
