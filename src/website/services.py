from core.services import (
    CreateMixin,
    DeleteMixin,
    ReadMixin,
    ServiceBase,
    UpdateMixin,
)
from core.utils.tree import HierarchyTree
from website.models import Media, Menu, Page, Widget
from website.schemas import (
    MediaCreateSchema,
    MenuCreateSchema,
    MenuUpdateSchema,
    PageCreateSchema,
    PageUpdateSchema,
    WidgetCreateSchema,
    WidgetUpdateSchema,
)
from website.website_widget import RendererWidgetRegistry, get_widget_type


class PageService(
    CreateMixin[PageCreateSchema],
    ReadMixin,
    UpdateMixin[PageUpdateSchema],
    DeleteMixin,
    ServiceBase[Page],
):
    """No hook needed.

    Everything `Model.save()` used to do to a page lives on `PageQuerySet`
    (`update_date`, `date_published`), so the admin and the service share the
    same invariants instead of each carrying half of them. Slug uniqueness is
    the `page_unique_slug` constraint, which
    `_database_error_to_validation_error` turns into a validation error.
    """

    async def read_published(self, filters=None, ordering=None, fields=None):
        """Pages a public visitor may see.

        Not an access rule: `apply_access_rules` assembles `Q` objects from the
        rules *granted* to the acting user's roles, and a website visitor is
        `user=None` with no role -- so the queryset would come back unfiltered
        and every draft would be public. Not a queryset on the view either: the
        last-updated-pages widget needs the same definition, and two copies of
        "published" is one too many.

        Deliberately not folded into `get_queryset()`: the admin and a future
        API must still be able to read drafts.
        """
        published = {"is_published": True}
        if filters:
            published.update(filters)
        return await self.read(published, ordering=ordering, fields=fields)


class MenuService(
    CreateMixin[MenuCreateSchema],
    ReadMixin,
    UpdateMixin[MenuUpdateSchema],
    DeleteMixin,
    ServiceBase[Menu],
):
    """`parent_path` upkeep lives on `MenuQuerySet`.

    Only the cycle guard is here, because it is the one rule that needs the
    record's current state -- which is exactly what `validate_data` is for.
    """

    def validate_data(self, data, instance):
        if "parent" not in data or instance is None:
            # No move, or a creation: a record that does not exist yet cannot be
            # its own ancestor, and its parent was resolved through `browse`, so
            # it necessarily exists.
            return

        parent = data["parent"]
        if parent is None:
            return  # unparenting to a root is always legal

        if parent.pk == instance.pk:
            raise self.ValidationError(
                "A menu item cannot be its own parent.", key="parent"
            )

        # `recompute_parent_store` walks *down* from the roots (`parent_id IS
        # NULL`), so a cycle is not an error there: the cycled rows simply
        # become unreachable, keep a stale `parent_path` and silently vanish
        # from every tree read. Nothing downstream would report it, so the
        # guard has to be here.
        #
        # `parent.parent_path` is the current path of the proposed parent, and
        # it contains `instance.pk` exactly when that parent already sits below
        # the instance. Costs no query: relation resolution handed us a loaded
        # instance.
        if str(instance.pk) in (parent.parent_path or "").split("/"):
            raise self.ValidationError(
                "A menu item cannot be moved under one of its own children.",
                key="parent",
            )

    async def read_tree(self, root_pk):
        """The subtree rooted at `root_pk` as a `TreeNode`, or None.

        Lives here rather than on the model -- where it used to be a classmethod
        -- because it is a read, and reads go through the service so that access
        rules apply.

        `Menu.url` dereferences `page.slug` and is evaluated while the template
        renders, out of reach of any `sync_to_async` hop, so the relation is
        resolved by this very query.
        """
        queryset = await self.read(
            filters={"parent_path__startswith": str(root_pk)},
            ordering=["sequence"],
        )
        # Narrowing a service queryset is allowed: access rules are already
        # baked in as `Q` objects, so a caller can only narrow it (see
        # `ServiceBase.browse`). `select_related` and not `prefetch_related`:
        # `page` is a forward foreign key, so one JOIN replaces a second query.
        # Not in `get_queryset()` either -- combined with a `read(fields=...)`
        # that defers `page`, django raises `FieldError`.
        queryset = queryset.select_related("page")

        tree = HierarchyTree()
        # One materialization hop, then a purely synchronous tree build.
        async for menu in queryset:
            tree.insert(menu.pk, menu.parent_id, menu)

        roots = tree.get_roots()
        # `get_roots()` returns [] on an empty tree, and the prefix filter
        # matches nothing when `root_pk` is not a top-level item -- a
        # `Website.menu` pointing at a child yields no root at all. Never index
        # into this blindly, which is what used to raise `IndexError` in the view.
        return roots[0] if roots else None


class WidgetService(
    CreateMixin[WidgetCreateSchema],
    ReadMixin,
    UpdateMixin[WidgetUpdateSchema],
    DeleteMixin,
    ServiceBase[Widget],
):
    """Carries the rule `Widget.clean()` holds.

    `clean()` is only ever called by a ModelForm, so the admin enforces the
    widget-type parameter rules and every other caller does not.
    """

    # The `param_*` fields, plus the type that decides which of them are legal.
    _widget_type_fields = ("widget_type", "param_content", "param_limit_item")

    def validate_data(self, data, instance):
        # An update carries only the fields actually set, so the rule has to be
        # evaluated on the merge of the payload and the stored row: changing the
        # type alone must still be checked against the parameters already there.
        values = {}
        for fname in self._widget_type_fields:
            if fname in data:
                values[fname] = data[fname]
            else:
                values[fname] = getattr(instance, fname, None) if instance else None

        # `choices` made the schema field an `Enum` whose members subclass
        # `str`. `.value` keeps the registry lookup readable; never `str()`,
        # which would yield "WidgetTypeEnum.CUSTOM_HTML".
        raw_type = values["widget_type"]
        widget_type = getattr(raw_type, "value", raw_type)
        values["widget_type"] = widget_type

        widget_type_instance = get_widget_type(widget_type)
        if widget_type_instance is None:
            # Unreachable through a schema -- the field is a `choices` enum
            # built from this very registry -- but reachable from a fixture or a
            # data migration, where `Widget.clean()` raises a bare
            # `AttributeError` today.
            raise self.ValidationError(
                f"Unknown widget type {widget_type!r}.", key="widget_type"
            )

        errors = widget_type_instance.get_validation_errors(values)
        if errors:
            raise self.ValidationError(errors)

    async def read_render_registry(self, position_prefix):
        """The widgets of one area, rendered, keyed by position.

        Everything a widget needs from the database is read *here*, in the async
        phase and through the services, because `RendererWidgetRegistry` is
        consumed while the template renders -- where a query would run outside
        any `sync_to_async` hop the service could open, and outside the access
        rules entirely.
        """
        queryset = await self.read(filters={"position__startswith": position_prefix})
        widgets = [widget async for widget in queryset]

        render_data = {}
        for widget in widgets:
            widget_type_instance = get_widget_type(widget.widget_type)
            if widget_type_instance is None:
                continue  # a stale type in the database renders as an empty slot
            render_data[widget.pk] = await widget_type_instance.aget_render_data(
                widget, self.env
            )

        return RendererWidgetRegistry(widgets, render_data)


class MediaService(
    CreateMixin[MediaCreateSchema],
    ReadMixin,
    DeleteMixin,
    ServiceBase[Media],
):
    """No update: a media is immutable.

    Replacing the bytes means creating a new record and deleting the old one,
    which keeps `checksum` honest and lets the storage reference-count the file.

    `checksum`, `mimetype` and `name` are derived by
    `MediaQuerySet.bulk_create`, and that is the only place they can be:

      * `validate_data` runs before `self.model(**values)` is built, so it would
        have to mutate the internal-values dict -- a write hidden in a
        validator;
      * `_create_postprocess` runs after the INSERT, too late for a NOT NULL
        column and after `FileField.pre_save` replaced `content.name` with the
        stored path;
      * overriding `create` does not help either: `_input_values` extracts along
        `create_schema`, so anything not declared there never reaches the
        values, and declaring `checksum`/`name`/`mimetype` on the create schema
        would make them client-writable -- precisely what must not happen.

    `_create_atomic` calls `self.get_queryset().bulk_create(...)`, so the
    queryset override sits on the service's own write path.
    """
