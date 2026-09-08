from django.test import TestCase

from website.models import Website


class TestWebsiteModel(TestCase):

    def test_primary_key_is_a_ulid(self):
        website = Website.objects.create(name="Moulinsart", headline="Le domaine")

        self.assertEqual(len(website.pk), 26)
        self.assertTrue(website.pk.isalnum())
