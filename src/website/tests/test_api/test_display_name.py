from django.test import TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.models import Media, Menu, Page


class WebsiteDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.hike = Page.objects.create(title="Le Hike", slug="hike", content="<p>x</p>", is_published=True)
        cls.draft = Page.objects.create(title="Atout Camp", slug="camp", content="<p>x</p>")
        cls.root = Menu.objects.create(name="Root", sequence=20)
        cls.activities = Menu.objects.create(name="Activities", parent=cls.root, sequence=25, link="#")
        # A checksum given: no file to read, nothing written to storage.
        cls.logo, cls.banner = Media.objects.bulk_create([
            Media(name="logo.png", content="website/logo.png", checksum="a" * 40),
            Media(name="banner.png", content="website/banner.png", checksum="b" * 40),
        ])

    def request(self, url, ids):
        return self.do_api_request(
            url, "GET", self.user_access_token_frodon.token, params={"id": ",".join(str(pk) for pk in ids)}
        )

    def test_pages(self):
        response = self.request("/api/v1/website/pages/display-name/", [self.draft.pk, self.hike.pk])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {"id": self.draft.pk, "title": "Atout Camp", "slug": "camp"},
                {"id": self.hike.pk, "title": "Le Hike", "slug": "hike"},
            ],
        )

    def test_menus(self):
        response = self.request("/api/v1/website/menus/display-name/", [self.activities.pk, self.root.pk])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"id": self.activities.pk, "name": "Activities"}, {"id": self.root.pk, "name": "Root"}],
        )

    def test_medias(self):
        response = self.request("/api/v1/website/medias/display-name/", [self.banner.pk, self.logo.pk])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [{"id": str(self.banner.pk), "name": "banner.png"}, {"id": str(self.logo.pk), "name": "logo.png"}],
        )

    @parameterized.expand(
        [
            ("/api/v1/website/pages/", "hike", "totem.websitepage.read", 200),
            ("/api/v1/website/pages/", "hike", "totem.websitemenu.read", 403),
            ("/api/v1/website/menus/", "root", "totem.websitemenu.read", 200),
            ("/api/v1/website/menus/", "root", "totem.websitemenu.update", 403),
            ("/api/v1/website/medias/", "logo", "totem.websitemedia.read", 200),
            ("/api/v1/website/medias/", "logo", "totem.websitepage.read", 403),
        ]
    )
    def test_access_rights(self, url, record, scope, status_code):
        self.user_access_token_frodon.scope = scope
        self.user_access_token_frodon.save(update_fields=["scope"])

        response = self.request(f"{url}display-name/", [getattr(self, record).pk])

        self.assertEqual(response.status_code, status_code)
