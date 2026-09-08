from django.test import TestCase

from website.models import Media


class TestMediaModel(TestCase):

    def test_primary_key_is_a_ulid(self):
        # `content` is given as a stored path rather than an upload: the pk is
        # the only concern here, and a real `File` would need `MEDIA_ROOT`
        # redirected the way `TestMediaService` does it.
        media = Media.objects.create(
            name="report.pdf", content="website/2024/10/report.pdf", checksum="abc"
        )

        self.assertEqual(len(media.pk), 26)
        self.assertTrue(media.pk.isalnum())
