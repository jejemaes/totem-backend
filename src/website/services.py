import mimetypes

from django.core import exceptions

from core.services import (
    CreateMixin,
    DeleteMixin,
    ReadMixin,
    ServiceBase,
    UpdateMixin,
)
from core.utils.tree import HierarchyTree
from website.models import Media, Menu, Page, Website
from website.schemas import (
    MediaCreateSchema,
    MenuCreateSchema,
    MenuUpdateSchema,
    PageCreateSchema,
    PageUpdateSchema,
    WebsiteUpdateSchema,
)


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

        Works at any depth. The prefix filter used to be `root_pk` itself, which
        only ever matched when `root_pk` was a top-level item: a `parent_path`
        starts at the top of the tree, so an inner node is the prefix of
        nothing. Reading the root's own path first costs one query and makes a
        `Website.menu` -- or a side-menu widget -- pointing at an inner item
        return its subtree instead of None.
        """
        root_queryset = await self.browse([root_pk])
        try:
            # `only`: the path is all this first query is for, the rows
            # themselves come back with the subtree.
            root = await root_queryset.only("parent_path").afirst()
        except (TypeError, ValueError, exceptions.ValidationError):
            # An ill-typed pk is "no such menu", not a crash: the caller may be
            # a widget marker carrying whatever string an author typed.
            return None
        if root is None:
            return None

        queryset = await self.read(
            filters={"parent_path__startswith": root.parent_path},
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
            # The root's own parent sits *outside* the subtree, so it is
            # inserted as a root itself: `HierarchyTree.insert` would otherwise
            # stand in an empty placeholder node for that parent, and the
            # placeholder -- not the root -- is what has no parent.
            parent_pk = None if menu.pk == root.pk else menu.parent_id
            tree.insert(menu.pk, parent_pk, menu)

        # Looked up by pk rather than through `get_roots()`: an access rule
        # hiding an intermediate item leaves a placeholder behind, and
        # `get_roots()` walks a dict, so which of the two it yields first is not
        # ours to decide. `.get` and not `[]`: the queryset comes back empty when
        # the root exists but the tree read is denied.
        return tree.node_map.get(root.pk)


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

    # NOT an allow-list, deliberately. `Media` is a general file store:
    # `upload_to` is "website/%Y/%m", `mimetype` is a free-form column, the
    # admin form writes through this service and its own tests file PDFs through
    # it. Restricting this to images would narrow the model to suit its newest
    # client -- the website's rich text editor -- and break every other writer.
    # The editor does its own narrowing, with `accept="image/*"` plus a
    # client-side check.
    #
    # What IS refused is the handful of types that EXECUTE when served. These
    # files go out from /media/public/ on the site's own origin, with no
    # Content-Disposition and no CSP, so an SVG or an HTML file there is a
    # stored-XSS vector rather than a document. A security floor, not a policy
    # about what the product accepts.
    REFUSED_MIMETYPES = frozenset(
        {
            "image/svg+xml",
            "text/html",
            "application/xhtml+xml",
            "application/xml",
            "text/xml",
        }
    )

    MAX_UPLOAD_SIZE = 5 * 1024 * 1024

    def validate_data(self, data, instance):
        """Size and executability, enforced here rather than anywhere else.

        Not on the model field: adding `validators=[...]` to a FileField changes
        its deconstruction and therefore generates a migration, for rules that
        are policy rather than schema.

        Not in the controller either: this is the one chokepoint every writer
        goes through -- the API, the admin form, and any future service caller.

        And the size check is NOT belt-and-braces. Nothing else in the stack
        refuses a large upload: nginx allows 300M and answers with an HTML 413
        rather than JSON, and Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` excludes
        file fields by design. Without this a 200 MB POST is accepted, streamed
        to disk and hashed twice.

        Running here also means a rejected upload writes NOTHING: this is before
        the INSERT and before `FileField.pre_save` commits the bytes, which
        would otherwise leave a `FileReference` row and a filestore symlink
        behind.
        """
        upload = data.get("content")
        if upload is None:
            # `MediaCreateSchema` annotates `content` as an `UploadedFile`, so a
            # missing or non-file value was already refused upstream.
            return

        if upload.size > self.MAX_UPLOAD_SIZE:
            raise self.ValidationError(
                f"The file is too large ({upload.size} bytes). "
                f"The maximum is {self.MAX_UPLOAD_SIZE} bytes.",
                key="content",
            )

        # Guessed from the FILENAME, deliberately, and not read from
        # `upload.content_type`: the filename guess is what
        # `Media.precompute_values` will actually store in the `mimetype`
        # column, so checking anything else would let the stored value disagree
        # with what was accepted. The declared content type is also the field a
        # caller fully controls.
        mimetype = mimetypes.guess_type(upload.name or "")[0]
        if mimetype in self.REFUSED_MIMETYPES:
            raise self.ValidationError(
                f"A {mimetype} file cannot be uploaded: it would execute script "
                f"when served from the site's own domain.",
                key="content",
            )


class WebsiteService(
    ReadMixin,
    UpdateMixin[WebsiteUpdateSchema],
    ServiceBase[Website],
):
    """The site's own settings: one row, read by every page of the public site.

    No `CreateMixin` and no `DeleteMixin`, and not for taste. The row is
    provisioned once by `WebsiteConfig.populate_system` under a fixed pk; a
    second row would make `read_current()` pick one of two identities by pk
    order, and deleting the only one takes `/` down. Nothing constrains the
    table at the database level on purpose either: the only constraint that
    really expresses "one row" is a `CheckConstraint` on the provisioned pk,
    which would forbid `Website.objects.create(...)` -- what the model tests and
    `WebsiteViewTestMixin.build_website` do -- and would bake an environment
    identifier into the schema. The absence of the two mixins IS the guard,
    which is why a test asserts it.

    No access rule either: `website.security` registers none, and
    `apply_access_rules` returns the queryset untouched for a model that has no
    rule. That is what lets the public render path -- `user=None`, no role --
    read the row at all. Registering a `BaseRule` for `Website` would blank the
    whole site.

    No `validate_data`: every field here is either free text or a relation, and
    a relation is already resolved through the related service's `browse`, so it
    is access-checked and reported as `RelationNotFound` without a hook. A
    consequence worth naming: an author holding only `website_manage_own_page`
    can set `homepage` to one of their own pages and to nothing else.

    Publication is deliberately NOT checked. `HomePageView.get_homepage`
    documents the opposite contract -- an unpublished or deleted homepage
    renders the hero alone rather than a 404 -- and refusing a draft would break
    the natural set-then-publish order.
    """

    async def read_current(self, fields=None):
        """The website record, or None on a database that has not been populated.

        `ordering=["id"]` for the same reason the view used to call `afirst()`:
        nothing constrains the table to one row, so the read must be
        deterministic rather than dependent on what the planner returns first.

        Callers on the render path must NOT pass `fields`. It becomes an
        `only()`, and the layout reads `name`/`headline` while the context mixin
        reads `menu_id`, `homepage_id` and `footer`; one name missing from that
        list is a `SynchronousOnlyOperation` raised inside the template render,
        which is what `test_async_safety` exists to catch. The controller is the
        one caller that may pass it, because `_response_orm_fields` derives the
        list from the response schema instead of guessing it.
        """
        queryset = await self.read(ordering=["id"], fields=fields)
        return await queryset.afirst()
