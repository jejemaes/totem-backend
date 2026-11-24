from user import choices as user_choices
from user.models import User, UserRole

USER_FRODON_ID = "c99199ba-8fa5-461e-802e-c303e390f61b"
USER_GOLLUM_ID = "401ac0f2-4abe-412c-acf8-9928f0f53edb"
USER_SAM_ID = "8632bc93-e692-43de-b873-34610551afcd"

# Roles of a user are unique per category, the part of the id before the first
# `_`: the two FELLOWSHIP roles cannot be held together.
ROLE_BASE_ID = "TEST_BASEUSER"
ROLE_HOBBIT_ID = "FELLOWSHIP_HOBBIT"
ROLE_WIZARD_ID = "FELLOWSHIP_WIZARD"
ROLE_ORC_ID = "MORDOR_ORC"


class UserServiceCommonMixin:
    """ Three users and four roles, every role granting nothing.

    Frodon is the acting user and holds `role` alone: an access rules test sets
    the rules it exercises on `role`, never a role of the fixtures. Gollum holds
    the Orc role, Sam none.

    Data only: the helpers are on `core.testing.ServiceTestCaseMixin`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.role, cls.role_hobbit, cls.role_wizard, cls.role_orc = UserRole.objects.bulk_create([
            UserRole(id=ROLE_BASE_ID, name="Role Test (Base)"),
            UserRole(id=ROLE_HOBBIT_ID, name="Hobbit"),
            UserRole(id=ROLE_WIZARD_ID, name="Wizard"),
            UserRole(id=ROLE_ORC_ID, name="Orc"),
        ])
        cls.user_frodon, cls.user_gollum, cls.user_sam = User.objects.bulk_create([
            User(
                id=USER_FRODON_ID,
                username="frodon@lacomte.com",
                email="frodon@lacomte.com",
                first_name="Frodon",
                last_name="Baggins",
                user_type=user_choices.UserType.INTERNAL,
            ),
            User(
                id=USER_GOLLUM_ID,
                username="gollum@precious.com",
                email="gollum@precious.com",
                first_name="Sméagol",
                user_type=user_choices.UserType.PORTAL,
            ),
            User(
                id=USER_SAM_ID,
                username="sam@lacomte.com",
                email="sam@lacomte.com",
                first_name="Samsagace",
                last_name="Gamgee",
                language="en-us",
                user_type=user_choices.UserType.INTERNAL,
            ),
        ])
        cls.user_frodon.roles.set([cls.role])
        cls.user_gollum.roles.set([cls.role_orc])
