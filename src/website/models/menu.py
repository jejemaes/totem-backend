from django.core.exceptions import EmptyResultSet
from django.db import connection, models
from django.db.models import Q

from core.orm.fields import ULIDField


class MenuQuerySet(models.QuerySet):
    """Materialized-path upkeep for the write paths that never call `save()`.

    `Menu.save()` computes `parent_path`, but the service layer inserts with
    `bulk_create` and writes with `queryset.update()`, neither of which calls
    it. Since `parent_path` is `null=False` with no default, a service creation
    would otherwise insert an empty path and silently drop the row out of every
    tree query.
    """

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        for obj in objs:
            if obj.pk is None:
                obj.pk = obj._meta.pk.get_default()
            if obj.parent_id:
                # Free on the service path: relation resolution
                # (`ServiceBase.to_internal_values`) already assigned a loaded
                # instance. A caller passing only `parent_id` pays one SELECT
                # per object, which is correct if not free.
                obj.parent_path = f"{obj.parent.parent_path}{obj.pk}/"
            else:
                obj.parent_path = f"{obj.pk}/"
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        """Recompute the paths when a move happened.

        Re-parenting moves an arbitrary subtree, so every path below it changes
        too. The recursive UPDATE walks the whole table in one statement and
        needs no read; scoping it to the moved subtrees would first cost a
        SELECT to capture the old paths, and a menu table is small by nature.

        `to_internal_values` puts the resolved instance under `parent`, while a
        direct ORM caller may pass `parent_id` -- hence both keys.
        """
        result = super().update(**kwargs)
        if "parent" in kwargs or "parent_id" in kwargs:
            self.model.recompute_parent_store(self.model.objects.all())
        return result


class Menu(models.Model):
    id = ULIDField("ID", primary_key=True)
    name = models.CharField(
        "Title", max_length=256, null=False, blank=False)
    parent = models.ForeignKey('website.Menu', null=True, blank=True, related_name="children", on_delete=models.PROTECT)
    # Indexed: every read of the tree is a `parent_path__startswith`, and on
    # postgres `db_index` on a CharField also creates the `varchar_pattern_ops`
    # index that actually serves a prefix search.
    parent_path = models.CharField("Parent Path", null=False, editable=False, db_index=True, max_length=256, help_text="Use to fetch all menu tree at once.")
    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    sequence = models.IntegerField("Sequence", default=20, null=False, help_text="Ordering menu items")
    # target
    page = models.ForeignKey('website.Page', verbose_name="Target Page", null=True,
                             blank=True, on_delete=models.PROTECT)
    link = models.CharField(
        "Target Link", max_length=256, null=True, blank=True)
    new_window = models.BooleanField(
        "Open in a new window", default=False, null=False, blank=True)

    objects = MenuQuerySet.as_manager()

    @property
    def url(self):
        if self.page_id:
            return f"/page/{self.page.slug}/"
        return self.link or '#'

    class Meta:
        verbose_name = "Menu Item"
        verbose_name_plural = "Menu Items"
        constraints = [
            models.CheckConstraint(
                check=(Q(parent__isnull=False) & (Q(link__isnull=False) | Q(page__isnull=False))) | (Q(parent__isnull=True)),
                name='%(class)s_page_or_link',
                violation_error_message="Menu must be linked to an URL or a page."
            ),
        ]

    def save(self, *args, **kwargs):
        old_parent_path = self.parent_path

        if self.parent:
            self.parent_path = f"{self.parent.parent_path}{self.pk}/"
        else:
            self.parent_path = f"{self.pk}/"

        super().save(*args, **kwargs)

        if old_parent_path:
            self.recompute_parent_store(type(self).objects.filter(parent_path__startswith=str(old_parent_path)))

    def __str__(self) -> str:  # pylint: disable=E0307
        return self.name

    @classmethod
    def recompute_parent_store(cls, qs):
        query = """
            WITH RECURSIVE __parent_store_compute(id, parent_path) AS (
                SELECT row.id, concat(row.id, '/')
                FROM website_menu row
                WHERE row.parent_id IS NULL
            UNION
                SELECT row.id, concat(comp.parent_path, row.id, '/')
                FROM website_menu row, __parent_store_compute comp
                WHERE row.parent_id = comp.id
            )
            UPDATE website_menu row SET parent_path = comp.parent_path
            FROM __parent_store_compute comp
            WHERE row.id = comp.id AND comp.id IN ({in_query})
        """
        try:
            in_query, in_query_params = (
                qs.values_list('pk', flat=True).query.sql_with_params()
            )
            with connection.cursor() as cursor:
                params = {
                    'in_query': in_query,
                }
                cursor.execute(
                    query.format(**params), in_query_params
                )
        except EmptyResultSet:
            # Django internal make the `.query.sql_with_params()` raise if no rows are matching
            # the where clause. This means no row should be updated, so we can ignore that.
            pass
