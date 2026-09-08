import json

from django.test import TestCase
from parameterized import parameterized

from core.testing import APITestCaseMixin
from user.tests.test_api.common import CommonTestMixin
from website.models import Page

ALL_SCOPES = (
    "totem.websitepage.create totem.websitepage.read "
    "totem.websitepage.update totem.websitepage.delete"
)


class PageAPITest(CommonTestMixin, APITestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.hike = Page.objects.create(
            title="Le Hike",
            slug="hike",
            content="<p>Mille sabords</p>",
            is_published=True,
            user=cls.user_frodon,
        )
        cls.draft = Page.objects.create(
            title="Atout Camp", slug="camp", content="<p>Tonnerre de Brest</p>"
        )

        cls.user_access_token_frodon.scope = ALL_SCOPES
        cls.user_access_token_frodon.save()

        cls.url = "/api/v1/website/pages/"

    @property
    def token(self):
        return self.user_access_token_frodon.token

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_api_request(self.url, "GET", self.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], 2)
        # Default ordering is by title.
        self.assertEqual(
            [item["title"] for item in data["results"]], ["Atout Camp", "Le Hike"]
        )

    def test_list_serializes_the_author_as_a_nested_object(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"slug": "hike"}
        )
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(item["user"]["id"], str(self.user_frodon.pk))

    def test_list_keeps_a_null_author(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"slug": "camp"}
        )
        item = response.json()["results"][0]

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(item["user"])

    @parameterized.expand([
        ({"search": "hike"}, ["Le Hike"]),
        ({"search": "camp"}, ["Atout Camp"]),
        ({"slug": "hike"}, ["Le Hike"]),
        ({"slug": "unknown"}, []),
        ({"is_published": True}, ["Le Hike"]),
        ({"is_published": False}, ["Atout Camp"]),
    ])
    def test_list_filters(self, filters, expected):
        response = self.do_api_request(self.url, "GET", self.token, params=filters)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["title"] for item in response.json()["results"]], expected
        )

    def test_list_filter_by_author(self):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"author": str(self.user_frodon.pk)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["title"] for item in response.json()["results"]], ["Le Hike"]
        )

    @parameterized.expand([
        ("title", ["Atout Camp", "Le Hike"]),
        ("-title", ["Le Hike", "Atout Camp"]),
        ("slug", ["Atout Camp", "Le Hike"]),
        ("update_date", ["Le Hike", "Atout Camp"]),
        ("-update_date", ["Atout Camp", "Le Hike"]),
    ])
    def test_list_ordering(self, ordering, expected):
        response = self.do_api_request(
            self.url, "GET", self.token, params={"ordering": ordering}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["title"] for item in response.json()["results"]], expected
        )

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_api_request(f"{self.url}{self.hike.pk}/", "GET", self.token)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["id"], self.hike.pk)
        self.assertEqual(len(data["id"]), 26)
        self.assertEqual(data["title"], "Le Hike")
        self.assertEqual(data["content"], "<p>Mille sabords</p>")
        self.assertIsNotNone(data["date_published"])

    def test_retrieve_unknown(self):
        response = self.do_api_request(
            f"{self.url}01ARZ3NDEKTSV4RRFFQ69G5FAV/", "GET", self.token
        )

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    def test_create(self):
        payload = {
            "title": "Le Camp Scout",
            "slug": "camp-scout",
            "content": "<p>Tonnerre de Brest</p>",
            "user": str(self.user_frodon.pk),
        }

        response = self.do_api_request(
            self.url, "POST", self.token, data=json.dumps(payload)
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertEqual(len(data["id"]), 26)
        self.assertEqual(data["user"]["id"], str(self.user_frodon.pk))

        page = Page.objects.get(pk=data["id"])
        self.assertEqual(page.slug, "camp-scout")
        self.assertFalse(page.is_published)
        self.assertIsNone(page.date_published)

    def test_create_published_stamps_the_publication_date(self):
        # `WebsitePublishedQuerySet.bulk_create`, which is the service write path.
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({
                "title": "Le Camp Scout",
                "slug": "camp-scout",
                "content": "<p>x</p>",
                "is_published": True,
            }),
        )
        data = response.json()

        self.assertEqual(response.status_code, 201, data)
        self.assertIsNotNone(data["date_published"])

    def test_create_with_a_duplicated_slug_is_rejected(self):
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({
                "title": "Another Hike", "slug": "hike", "content": "<p>x</p>",
            }),
        )

        # The `page_unique_slug` constraint, mapped by
        # `_database_error_to_validation_error` and its violation message.
        self.assertEqual(response.status_code, 422, response.json())
        self.assertIn("slug already exists", json.dumps(response.json()))
        self.assertEqual(Page.objects.filter(slug="hike").count(), 1)

    def test_create_with_invalid_html_is_rejected(self):
        # The `HtmlField` validators become pydantic validators on the schema,
        # so the content never reaches the service.
        response = self.do_api_request(
            self.url, "POST", self.token,
            data=json.dumps({
                "title": "Nope",
                "slug": "nope",
                "content": "<p onclick=\"alert('yolo')\">x</p>",
            }),
        )

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Page.objects.filter(slug="nope").exists())

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    def test_update_moves_the_update_date(self):
        before = Page.objects.get(pk=self.draft.pk)

        response = self.do_api_request(
            f"{self.url}{self.draft.pk}/", "PATCH", self.token,
            data=json.dumps({"title": "Renamed"}),
        )

        self.assertEqual(response.status_code, 200, response.json())
        after = Page.objects.get(pk=self.draft.pk)
        self.assertEqual(after.title, "Renamed")
        # `queryset.update()` does not run `auto_now`; `PageQuerySet` does.
        self.assertGreater(after.update_date, before.update_date)

    def test_update_publishing_stamps_the_publication_date(self):
        response = self.do_api_request(
            f"{self.url}{self.draft.pk}/", "PATCH", self.token,
            data=json.dumps({"is_published": True}),
        )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertIsNotNone(Page.objects.get(pk=self.draft.pk).date_published)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete(self):
        response = self.do_api_request(
            f"{self.url}{self.draft.pk}/", "DELETE", self.token
        )

        self.assertIn(response.status_code, (200, 204))
        self.assertFalse(Page.objects.filter(pk=self.draft.pk).exists())

    # ------------------------------------------
    # Permissions
    # ------------------------------------------

    @parameterized.expand([
        ("GET", "totem.websitepage.create"),
        ("POST", "totem.websitepage.read"),
        ("PATCH", "totem.websitepage.read"),
        ("DELETE", "totem.websitepage.read"),
    ])
    def test_operation_requires_its_own_scope(self, method, wrong_scope):
        self.user_access_token_frodon.scope = wrong_scope
        self.user_access_token_frodon.save()
        url = self.url if method in ("GET", "POST") else f"{self.url}{self.draft.pk}/"
        # A valid body: ninja validates it before the view runs, so an empty one
        # would answer 422 without ever reaching the permission check.
        body = json.dumps({"title": "Nope", "slug": "nope", "content": "<p>x</p>"})

        response = self.do_api_request(url, method, self.token, data=body)

        self.assertEqual(response.status_code, 403)
