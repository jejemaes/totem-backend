from contact.models import ContactTag
from user.tests.test_services.common_user import UserServiceCommonMixin

TAG_FELLOWSHIP_ID = "01JT0000000000000000000001"
TAG_HOBBIT_ID = "01JT0000000000000000000002"
TAG_WIZARD_ID = "01JT0000000000000000000003"

TAG_UNKNOWN_ID = "01JT0000000000000000000099"


class ContactTagServiceCommonMixin(UserServiceCommonMixin):
    """ Three tags, on top of the users of `user`: Fellowship (color 3), Hobbit
    (5) and Wizard (9). Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tag_fellowship, cls.tag_hobbit, cls.tag_wizard = ContactTag.objects.bulk_create([
            ContactTag(id=TAG_FELLOWSHIP_ID, name="Fellowship", color=3),
            ContactTag(id=TAG_HOBBIT_ID, name="Hobbit", color=5),
            ContactTag(id=TAG_WIZARD_ID, name="Wizard", color=9),
        ])
