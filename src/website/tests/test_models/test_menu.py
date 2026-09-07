from django.test import TestCase

from website.models import Menu


class TestMenuModel(TestCase):
    """The historical write path, which the admin still uses.

    The service writes through `MenuQuerySet`, so these cover the other half:
    `Model.save()` must keep computing the materialized path on its own.
    """

    @classmethod
    def setUpTestData(cls):
        cls.root = Menu.objects.create(name="Root")

    def test_save_materializes_the_path(self):
        child = Menu.objects.create(name="Child", parent=self.root, link="/a/")

        self.assertEqual(child.parent_path, f"{self.root.pk}/{child.pk}/")

    def test_bulk_create_materializes_the_path(self):
        # Direct ORM `bulk_create`, no service: the override is on the queryset
        # precisely so every caller gets it.
        menu = Menu(name="Child", parent=self.root, link="/a/")
        Menu.objects.bulk_create([menu])

        self.assertEqual(
            Menu.objects.get(pk=menu.pk).parent_path,
            f"{self.root.pk}/{menu.pk}/",
        )

    def test_queryset_update_of_the_parent_recomputes_the_subtree(self):
        other_root = Menu.objects.create(name="Other Root")
        child = Menu.objects.create(name="Child", parent=self.root, link="/a/")
        grandchild = Menu.objects.create(name="Grandchild", parent=child, link="/b/")

        Menu.objects.filter(pk=child.pk).update(parent=other_root)

        self.assertEqual(
            Menu.objects.get(pk=grandchild.pk).parent_path,
            f"{other_root.pk}/{child.pk}/{grandchild.pk}/",
        )
