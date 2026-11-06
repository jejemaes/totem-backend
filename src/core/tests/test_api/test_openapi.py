from django.test import SimpleTestCase
from ninja import NinjaAPI

from core.api import BaseController, route
from totem.api import api_v1


class TagGroupsTest(SimpleTestCase):
    """`x-tagGroups` of the documentation: the tags of each controller, filed under
    its `tag_group`, by default the `verbose_name` of its app."""

    def tag_groups(self, api):
        # `path_prefix` given: the throwaway API has no URL to reverse its root from.
        schema = api.get_openapi_schema(path_prefix="")
        return {group["name"]: group["tags"] for group in schema["x-tagGroups"]}

    def test_default_is_app_verbose_name(self):
        groups = self.tag_groups(api_v1)

        self.assertIn("Contact", groups["Contacts"])
        self.assertIn("Contact Tag", groups["Contacts"])
        self.assertIn("API Key", groups["Authentication"])

    def test_every_tag_is_grouped(self):
        # Redoc hides a tag that belongs to no group.
        schema = api_v1.get_openapi_schema()
        grouped = {tag for group in schema["x-tagGroups"] for tag in group["tags"]}
        used = {
            tag
            for path in schema["paths"].values()
            for operation in path.values()
            for tag in operation.get("tags", [])
        }

        self.assertEqual(used - grouped, set())

    def test_override_and_merge(self):
        test_api = NinjaAPI(urls_namespace="test_tag_groups")

        class FirstController(BaseController):
            api = test_api
            path_prefix = "/first/"
            tag_group = "Custom"

            @route.get("/", response=str, tags=["First"])
            async def first(self, request):
                return ""

        class SecondController(BaseController):
            api = test_api
            path_prefix = "/second/"
            tag_group = "Custom"

            @route.get("/", response=str, tags=["First", "Second"])
            async def second(self, request):
                return ""

        class DefaultController(BaseController):
            api = test_api
            path_prefix = "/default/"

            @route.get("/", response=str, tags=["Default"])
            async def default(self, request):
                return ""

        self.assertEqual(
            self.tag_groups(test_api),
            {"Custom": ["First", "Second"], "Internal": ["Default"]},
        )
