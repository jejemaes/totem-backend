from user.tests.test_services.common_user import UserServiceCommonMixin

PASSWORD = "a-perfectly-fine-password"


class AuthServiceCommonMixin(UserServiceCommonMixin):
    """ On top of the users of `user`: Frodon has a password, and his role reads
    the users and the contacts. Gollum is deactivated, with the same password.
    Sam keeps the unusable password `User.objects.create()` leaves. Data only. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.role.permissions = ["totem.user.read", "totem.contact.read"]
        cls.role.save(update_fields=["permissions"])
        for user in (cls.user_frodon, cls.user_gollum):
            user.set_password(PASSWORD)
        cls.user_gollum.is_active = False
        cls.user_frodon.save(update_fields=["password"])
        cls.user_gollum.save(update_fields=["password", "is_active"])
