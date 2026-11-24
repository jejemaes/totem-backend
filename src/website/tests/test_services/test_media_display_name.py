from asgiref.sync import async_to_sync
from django.test import TestCase
from parameterized import parameterized

from core.testing import ServiceTestCaseMixin
from website.services import MediaService

from website.tests.test_services.common_media import (
    MEDIA_BOOK_ID,
    MEDIA_MAP_ID,
    MEDIA_UNKNOWN_ID,
    MediaServiceCommonMixin,
)


class MediaDisplayNameServiceTest(MediaServiceCommonMixin, ServiceTestCaseMixin, TestCase):
    """ No access rules tests: no `BaseRule` is registered for `Media`. """

    def setUp(self):
        super().setUp()
        self.service = self.get_service(MediaService, user=self.user_frodon)

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The roles of the acting user, then the media.
            ("one pk", [MEDIA_BOOK_ID], 2, [MEDIA_BOOK_ID]),
            ("in the order of the pks", [MEDIA_BOOK_ID, MEDIA_MAP_ID], 2, [MEDIA_BOOK_ID, MEDIA_MAP_ID]),
            ("a repeated pk appears once", [MEDIA_BOOK_ID, MEDIA_BOOK_ID], 2, [MEDIA_BOOK_ID]),
            ("an unknown pk is absent", [MEDIA_UNKNOWN_ID, MEDIA_BOOK_ID], 2, [MEDIA_BOOK_ID]),
            # A ULID field coerces any string: it reaches the database.
            ("a malformed pk is absent", ["not-a-ulid"], 2, []),
            ("no pk", [], 0, []),
        ]
    )
    def test_display_name(self, label, pks, query_count, expected_pks):
        with self.assertNumQueries(query_count):
            medias = async_to_sync(self.service.display_name)(pks, ["id", "name"])

        self.assertEqual([media.pk for media in medias], expected_pks)
        for media in medias:
            self.assertNotIn("name", media.get_deferred_fields())
            self.assertIn("content", media.get_deferred_fields())
