import hashlib

from django.core.files.uploadedfile import SimpleUploadedFile

from core.testing import MediaRootTestMixin
from user.tests.test_services.common_user import UserServiceCommonMixin
from website.models import Media

MEDIA_MAP_ID = "01M209K5BNS12QRPHXFWVJNVA1"
MEDIA_BOOK_ID = "01M209K5BNS12QRPHXFWVJNVA2"

MEDIA_UNKNOWN_ID = "01M209K5BNS12QRPHXFWVJNVA9"

PAYLOAD = b"%PDF-1.4 not really a pdf"
PAYLOAD_SHA1 = hashlib.sha1(PAYLOAD).hexdigest()


def upload(filename="red-book.pdf", payload=PAYLOAD, content_type="application/pdf"):
    return SimpleUploadedFile(filename, payload, content_type=content_type)


class MediaServiceCommonMixin(MediaRootTestMixin, UserServiceCommonMixin):
    """ Two media, on top of the users of `user`: "map-of-the-shire.png", an
    image, and "red-book.pdf". Their checksums are given and their content is a
    bare path: nothing is read from or written to the storage, so they serve the
    reads, not the deletes -- a test reaching the storage uploads its own file,
    through the service, in the temporary `MEDIA_ROOT`. Data only.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.media_map, cls.media_book = Media.objects.bulk_create([
            Media(
                id=MEDIA_MAP_ID, name="map-of-the-shire.png", content="website/map-of-the-shire.png",
                mimetype="image/png", checksum="a" * 40,
            ),
            Media(
                id=MEDIA_BOOK_ID, name="red-book.pdf", content="website/red-book.pdf",
                mimetype="application/pdf", checksum="b" * 40,
            ),
        ])
