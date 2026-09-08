from asgiref.sync import async_to_sync
from django.db.models import ProtectedError
from django.test import TestCase

from core.services import Environment
from core.services.exceptions import ServiceValidationMultiError
from website.models import Menu, Page
from website.schemas import MenuCreateSchema, MenuFilterSchema, MenuUpdateSchema
from website.services import MenuService


class TestMenuService(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Created through `save()`, so their own paths are set the historical way.
        cls.root = Menu.objects.create(name="Root")
        cls.other_root = Menu.objects.create(name="Other Root")
        cls.page = Page.objects.create(
            title="Page", slug="page", content="<p>x</p>"
        )

    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(MenuService)

    def _create(self, **kwargs):
        return async_to_sync(self.service.create)([MenuCreateSchema(**kwargs)])[0]

    # ------------------------------------------
    # Tests Create
    # ------------------------------------------

    def test_create_a_root_item_materializes_its_own_path(self):
        # `parent_path` is `null=False` with no default, and the service inserts
        # through `bulk_create`, which never calls the `save()` that computes it.
        menu = self._create(name="New Root")

        self.assertEqual(
            Menu.objects.get(pk=menu.pk).parent_path, f"{menu.pk}/"
        )

    def test_create_a_child_materializes_the_full_path(self):
        menu = self._create(name="Child", parent=str(self.root.pk), link="/a/")

        self.assertEqual(
            Menu.objects.get(pk=menu.pk).parent_path,
            f"{self.root.pk}/{menu.pk}/",
        )

    def test_create_a_grandchild_materializes_the_full_path(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        grandchild = self._create(name="Grandchild", parent=str(child.pk), link="/b/")

        self.assertEqual(
            Menu.objects.get(pk=grandchild.pk).parent_path,
            f"{self.root.pk}/{child.pk}/{grandchild.pk}/",
        )

    def test_create_resolves_the_target_page_through_its_service(self):
        menu = self._create(name="Child", parent=str(self.root.pk), page=self.page.pk)

        self.assertEqual(Menu.objects.get(pk=menu.pk).page_id, self.page.pk)

    def test_create_with_an_unknown_parent_is_rejected(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self._create(
                name="Child",
                # Well-formed but absent: `MenuCreateSchema.parent` borrows the
                # constraints of the target primary key, so a string longer than
                # 26 characters would be rejected before the service runs.
                parent="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                link="/a/",
            )

        self.assertIn("parent", ctx.exception.dict()[0])

    def test_create_a_child_without_a_link_or_a_page_is_rejected(self):
        with self.assertRaises(ServiceValidationMultiError) as ctx:
            self._create(name="Child", parent=str(self.root.pk))

        # `menu_page_or_link`, surfaced through its `violation_error_message`.
        self.assertIn(
            "Menu must be linked to an URL or a page.",
            str(ctx.exception.dict()["__all__"]),
        )

    def test_create_a_root_without_a_link_or_a_page_is_allowed(self):
        # The constraint exempts roots: they are containers, not destinations.
        menu = self._create(name="New Root")

        self.assertTrue(Menu.objects.filter(pk=menu.pk).exists())

    def test_the_materialized_path_is_not_writable(self):
        for schema in (MenuCreateSchema, MenuUpdateSchema):
            self.assertNotIn("parent_path", schema.model_fields)

    # ------------------------------------------
    # Tests Update
    # ------------------------------------------

    def test_moving_an_item_recomputes_its_whole_subtree(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        grandchild = self._create(name="Grandchild", parent=str(child.pk), link="/b/")

        async_to_sync(self.service.update)(
            {"id": child.pk}, MenuUpdateSchema(parent=str(self.other_root.pk))
        )

        # The moved row *and* everything below it: the recursive recompute is
        # what makes the descendants follow.
        self.assertEqual(
            Menu.objects.get(pk=child.pk).parent_path,
            f"{self.other_root.pk}/{child.pk}/",
        )
        self.assertEqual(
            Menu.objects.get(pk=grandchild.pk).parent_path,
            f"{self.other_root.pk}/{child.pk}/{grandchild.pk}/",
        )

    def test_unparenting_an_item_makes_it_a_root(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        grandchild = self._create(name="Grandchild", parent=str(child.pk), link="/b/")

        async_to_sync(self.service.update)(
            {"id": child.pk}, MenuUpdateSchema(parent=None)
        )

        self.assertEqual(
            Menu.objects.get(pk=child.pk).parent_path, f"{child.pk}/"
        )
        self.assertEqual(
            Menu.objects.get(pk=grandchild.pk).parent_path,
            f"{child.pk}/{grandchild.pk}/",
        )

    def test_updating_a_plain_field_leaves_the_path_alone(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        path = Menu.objects.get(pk=child.pk).parent_path

        async_to_sync(self.service.update)(
            {"id": child.pk}, MenuUpdateSchema(name="Renamed")
        )

        self.assertEqual(Menu.objects.get(pk=child.pk).parent_path, path)

    def test_an_item_cannot_become_its_own_parent(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": child.pk}, MenuUpdateSchema(parent=str(child.pk))
            )

        self.assertIn("parent", ctx.exception.dict()[child.pk])
        self.assertEqual(
            Menu.objects.get(pk=child.pk).parent_path,
            f"{self.root.pk}/{child.pk}/",
        )

    def test_an_item_cannot_be_moved_under_its_own_child(self):
        # Without the guard this is not an error anywhere downstream: the
        # recursive recompute walks *down* from the roots, so the cycled rows
        # simply become unreachable, keep a stale path and vanish from every
        # tree read.
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        grandchild = self._create(name="Grandchild", parent=str(child.pk), link="/b/")

        with self.assertRaises(ServiceValidationMultiError) as ctx:
            async_to_sync(self.service.update)(
                {"id": child.pk}, MenuUpdateSchema(parent=str(grandchild.pk))
            )

        self.assertIn("parent", ctx.exception.dict()[child.pk])
        self.assertEqual(
            Menu.objects.get(pk=grandchild.pk).parent_path,
            f"{self.root.pk}/{child.pk}/{grandchild.pk}/",
        )

    # ------------------------------------------
    # Tests Read
    # ------------------------------------------

    def test_the_tree_reads_back_what_the_service_created(self):
        # End-to-end proof that the materialized path is right: `read_tree`
        # depends on it entirely, and a wrong path loses the node silently.
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        grandchild = self._create(name="Grandchild", parent=str(child.pk), link="/b/")

        root_node = async_to_sync(self.service.read_tree)(self.root.pk)

        self.assertEqual(root_node.data.pk, self.root.pk)
        self.assertEqual([n.data.pk for n in root_node.children], [child.pk])
        self.assertEqual(
            [n.data.pk for n in root_node.children[0].children], [grandchild.pk]
        )

    def test_the_tree_is_none_when_the_root_has_no_item(self):
        # `read_tree` on a pk that is not a top-level item matches nothing, and
        # on an empty table there is no root at all. Indexing blindly into
        # `get_roots()` is what used to raise `IndexError` in the view.
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")

        self.assertIsNone(async_to_sync(self.service.read_tree)(child.pk))

    def test_the_tree_resolves_the_target_page_in_one_query(self):
        # `Menu.url` reads `page.slug` while the template renders, out of reach
        # of any `sync_to_async` hop, so the relation must come back with the
        # tree -- hence `select_related` and not a second query per node.
        self._create(name="Child", parent=str(self.root.pk), page=self.page.pk)

        with self.assertNumQueries(1):
            root_node = async_to_sync(self.service.read_tree)(self.root.pk)
            for node in root_node.children:
                node.data.url

    def test_the_tree_orders_by_sequence(self):
        second = self._create(
            name="Second", parent=str(self.root.pk), link="/b/", sequence=20
        )
        first = self._create(
            name="First", parent=str(self.root.pk), link="/a/", sequence=10
        )

        root_node = async_to_sync(self.service.read_tree)(self.root.pk)

        self.assertEqual(
            [n.data.pk for n in root_node.children], [first.pk, second.pk]
        )

    def test_read_filters_on_a_whole_subtree(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")
        self._create(name="Elsewhere", parent=str(self.other_root.pk), link="/c/")

        queryset = async_to_sync(self.service.read)(
            MenuFilterSchema(root=str(self.root.pk))
        )

        self.assertEqual(
            {m.pk for m in queryset}, {self.root.pk, child.pk}
        )

    # ------------------------------------------
    # Tests Delete
    # ------------------------------------------

    def test_delete_a_leaf(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")

        async_to_sync(self.service.delete)({"id": child.pk})

        self.assertFalse(Menu.objects.filter(pk=child.pk).exists())

    def test_delete_a_parent_is_refused(self):
        child = self._create(name="Child", parent=str(self.root.pk), link="/a/")

        # `Menu.parent` is `PROTECT`; see the note in `test_page`.
        with self.assertRaises(ProtectedError):
            async_to_sync(self.service.delete)({"id": self.root.pk})

        self.assertTrue(Menu.objects.filter(pk=child.pk).exists())
