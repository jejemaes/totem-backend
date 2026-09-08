from django.test import Client, TestCase
from django.urls import reverse

from website.models import Page, Website
from website.views import HomePageView

from .common import WebsiteViewTestMixin


class TestHomePageView(WebsiteViewTestMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.page = self.build_page()
        self.homepage = self.build_page(slug="home", content="<div><p>hello</p></div>")
        self.menu = self.build_menu_tree(page=self.page)
        self.website = self.build_website(menu=self.menu, homepage=self.homepage)

    def test_homepage_renders(self):
        response = Client().get(reverse("homepage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Moulinsart")

    # ------------------------------------------
    # Tests Graceful Degradation
    # ------------------------------------------

    def test_homepage_without_website_record(self):
        # `Website.objects.afirst()` returns None on a database that has not
        # been populated, and reading `.menu_id` on it used to raise
        # `AttributeError`.
        Website.objects.all().delete()

        response = Client().get(reverse("homepage"))

        self.assertEqual(response.status_code, 200)

    def test_homepage_without_a_main_menu(self):
        # The template walked `menu_tree.children`, and jinja raises
        # `UndefinedError` on a None tree -- the branch the code already took
        # whenever `menu_id` was unset.
        Website.objects.filter(pk=self.website.pk).update(menu=None)

        response = Client().get(reverse("homepage"))

        self.assertEqual(response.status_code, 200)

    def test_homepage_without_a_homepage_page(self):
        # A freshly provisioned system has a `Website` row but no content: `/`
        # must still answer, with the hero alone.
        Website.objects.filter(pk=self.website.pk).update(homepage=None)

        response = Client().get(reverse("homepage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Moulinsart")

    def test_homepage_with_an_unpublished_homepage(self):
        # Unpublishing the homepage must not 404 the root of the site.
        Page.objects.filter(pk=self.homepage.pk).update(is_published=False)

        response = Client().get(reverse("homepage"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "hello")

    def test_the_homepage_content_is_rendered(self):
        response = Client().get(reverse("homepage"))

        self.assertContains(response, "hello")

    def test_the_homepage_page_can_not_be_deleted_while_the_site_points_at_it(self):
        from django.db.models import ProtectedError

        with self.assertRaises(ProtectedError):
            self.homepage.delete()

    def test_homepage_with_a_menu_root_that_is_not_a_root(self):
        # The subtree filter matches nothing, so there is no root to index into
        # -- which used to be an `IndexError`.
        child = self.menu.children.first()
        Website.objects.filter(pk=self.website.pk).update(menu=child)

        response = Client().get(reverse("homepage"))

        self.assertEqual(response.status_code, 200)

    # ------------------------------------------
    # Tests Render Is Not A Query Phase
    # ------------------------------------------

    def test_render_makes_no_query(self):
        # The point of the whole refactor. The template renders outside any
        # `sync_to_async` hop, so anything left lazy here queries the database
        # past the service layer and past its access rules.
        Page.objects.filter(pk=self.homepage.pk).update(
            content=f"<div><p>hello</p>{self.marker(attrs={'limit': 3})}</div>"
        )
        Website.objects.filter(pk=self.website.pk).update(
            footer=f"<div>{self.marker()}</div>"
        )

        response = self.get_unrendered_response(HomePageView, "/")

        with self.assertNumQueries(0):
            response.render()
        self.assertEqual(response.status_code, 200)

    def test_the_menu_nodes_are_materialised(self):
        response = self.get_unrendered_response(HomePageView, "/")

        nodes = response.context_data["menu_nodes"]
        self.assertIsInstance(nodes, list)
        with self.assertNumQueries(0):
            # `Menu.url` dereferences `page.slug`: resolved by `read_tree`'s
            # `select_related`, not by a query per node during the render.
            for node in nodes:
                node.data.url

    def test_a_lazy_value_in_the_render_context_is_refused(self):
        class LeakyHomePageView(HomePageView):
            async def get_website_context_data(self):
                from website.models import Page
                context = await super().get_website_context_data()
                context["leak"] = Page.objects.all()
                return context

        with self.assertRaises(TypeError) as ctx:
            self.get_unrendered_response(LeakyHomePageView, "/")

        self.assertIn("lazy", str(ctx.exception))
