from unittest.mock import patch

from django.test import TestCase

from user import choices
from user.models import User

USER_ID1 = "14041cce-8719-4637-92b1-51c4ade4b643"
USER_ID2 = "25f50950-7228-4f40-a68f-3aafdb4e1b67"
USER_ID3 = "3d9afc04-8ac2-40be-83de-a3c3e171923c"


class TestUserModel(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user_1 = User.objects.create(
            pk=USER_ID1,
            username="Tintin",
            password="MiL0u4ev3r",
            email="tintin@moulinsart.com",
        )
        cls.user_2 = User.objects.create(
            pk=USER_ID2,
            username="Haddock",
            password="MilleMilliardDeMillesabords",
            email="capitain@moulinsart.com",
        )
        cls.user_3 = User.objects.create(
            pk=USER_ID3,
            username="proftournesol",
            password="ObjectIfLuN3",
            email="trifon@moulinsart.com",
        )

    # ------------------------------------------
    # Tests signals
    # ------------------------------------------

    @patch('user.signals.user_change_rights.send')
    def test_signal_instance_create(
        self, mock
    ):
        user = User(username="testme", password="secret", email="test@test.com")
        user.save()

        self.assertEqual(mock.call_count, 0)

    @patch('user.signals.user_change_rights.send')
    def test_signal_instance_update(
        self, mock
    ):
        def side_effect_assert(sender=None, user_qs=None):
            ids = [str(pk) for pk in user_qs.values_list('id', flat=True)]
            self.assertEqual([USER_ID1], ids)

        mock.side_effect = side_effect_assert

        self.user_1.user_type = choices.UserType.ADMIN
        self.user_1.save(update_fields=['user_type'])

        self.assertEqual(mock.call_count, 1)

    @patch('user.signals.user_change_rights.send')
    def test_signal_instance_delete(
        self, mock
    ):
        self.user_1.delete()

        self.assertEqual(mock.call_count, 0)

    @patch('user.signals.user_change_rights.send')
    def test_signal_queryset_create(
        self, mock
    ):
        user = User(username="testme", password="secret", email="test@test.com")
        User.objects.bulk_create([user])

        self.assertEqual(mock.call_count, 0)

    @patch('user.signals.user_change_rights.send')
    def test_signal_queryset_update(
        self, mock
    ):
        def side_effect_assert(sender=None, user_qs=None):
            # A set: the queryset has no ordering, so its rows come in whatever
            # order the table holds them, which earlier tests leave behind.
            ids = {str(pk) for pk in user_qs.values_list('id', flat=True)}
            self.assertEqual({USER_ID1, USER_ID2}, ids)

        mock.side_effect = side_effect_assert

        users = User.objects.filter(pk__in=[USER_ID1, USER_ID2])
        users.update(user_type=choices.UserType.ADMIN)

        self.assertEqual(mock.call_count, 1)

    @patch('user.signals.user_change_rights.send')
    def test_signal_queryset_delete(
        self, mock
    ):
        users = User.objects.filter(pk__in=[USER_ID1, USER_ID2])
        users.delete()

        self.assertEqual(mock.call_count, 0)
