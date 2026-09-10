# The layer contract

## Table of contents

- [Environment: the per-request service container](#environment)
- [Services: the only ORM access](#services)
- [Access rules](#access-rules)
- [Schemas](#schemas)
- [Controllers](#controllers)
- [Where each kind of rule lives](#where-each-kind-of-rule-lives)
- [Startup wiring](#startup-wiring)
- [App file layout](#app-file-layout)

## Environment

`core.services.Environment` is a per-request container holding the acting user
and memoising service instances. `env.get(PageService)` is how you get one;
never instantiate a service directly.

- In a controller: `request.env.get(self.service)`.
- In an SSR view: `self.env.get(...)`, provided by `core.views.mixins.EnvironmentViewMixin`.
- In a test: `Environment(user).get(SomeService)`, or `Environment(None)` for an
  anonymous visitor.
- Inside a widget's `get_render_context`: the `env` argument.

`Environment.get_access_roles()` issues no query when `user is None`, which is
why the public website costs nothing extra for being routed through services.

## Services

One service per model, auto-registered by `ServiceBase.__init_subclass__` and
validated at startup. Declared with generics, and the model is inferred from
`ServiceBase[...]`:

```python
class PageService(
    CreateMixin[PageCreateSchema],
    ReadMixin,
    UpdateMixin[PageUpdateSchema],
    DeleteMixin,
    ServiceBase[Page],
):
```

Compose only the operations the resource actually has. **The absence of a mixin
is the guard**, and it is often the only one — `WebsiteService` omits
`CreateMixin` and `DeleteMixin` to express "one row, provisioned once", because
the only database constraint that would say the same thing is a
`CheckConstraint` on a hardcoded pk. When absence carries meaning like that, say
so in the docstring and pin it with a test (`assertFalse(hasattr(Service, "create"))`).

Surfaces:

- `read(filters, ordering, fields)` — the rich opt-in read for controllers.
- `browse(pks)` — the minimal capability every service owes the others; relation
  resolution goes through it, so it exists whatever else is composed.
- `create(data)` / `update(filters, data)` / `delete(filters)` — take *schema
  instances*, not dicts.
- `validate_data(data, instance)` — the business-rule hook.

A named read is the right way to express a narrower view of the data
(`PageService.read_published`). Put it on the service, not in the caller: two
callers with two copies of "published" is one too many.

`fields=` becomes `.only()` plus `prefetch_related()`. For an async route that
is a correctness requirement, not an optimisation: ninja serializes outside any
`sync_to_async` hop, so a deferred field or unresolved relation raises
`SynchronousOnlyOperation` there. Controllers get the right list from
`self._response_orm_fields(schema)`. **SSR views must not pass `fields=`** — the
template reads names the view does not know about.

## Access rules

A `BaseRule` in `<app>/security.py` declares `model`, `operations` and a
`scope_filter(context) -> Q`. `apply_access_rules` assembles the `Q` objects of
the rules *granted to the acting user's roles*.

Two consequences that are easy to get backwards:

- **A model with no rule registered is readable by everyone**, because there is
  nothing to assemble. That is what lets the anonymous public site read
  `Website`. Registering a first rule for such a model silently removes public
  access.
- **A rule cannot express "public visitors see only published records"**, because
  a visitor is `user=None` with no role, so nothing filters. Publication is a
  named read on the service (`read_published`), not a rule. Getting this wrong
  makes every draft public.

## Schemas

`core.schemas.ModelSchema` with a `Meta` naming `model`, `fields` and
`optional_fields`. Per resource:

| Schema | Role |
|---|---|
| `*DisplayNameSchema` | what a relation to this model serializes to |
| `*Schema` | the read response |
| `*CreateSchema` | POST body — omit derived and server-owned fields |
| `*UpdateSchema` | PATCH body, usually `optional_fields = "__all__"` |
| `*FilterSchema` | ninja `FilterSchema`, `q=` lookups |

Points that bite:

- Annotate relations explicitly or they serialize as bare pks and are not
  prefetched.
- A derived or non-ORM value must not be in a response schema:
  `apply_query_fields` resolves every requested lookup through
  `model._meta.get_field()`, so a property there breaks any client passing
  `?fields=`. `Page.url` is excluded for exactly this reason.
- `optional_fields = "__all__"` types every field `Optional`, so a client can
  send `null` into a NOT NULL column. `to_internal_values` turns that into a
  field error; without it you would get an unkeyed integrity error.
- A field named `schema` shadows a pydantic attribute — name it something else
  (`attribute_schema`, `option_schema`).
- Document the schemas you deliberately did **not** write, and why. Every
  existing schema module does this in a trailing comment.

## Controllers

Routes, scopes and response shapes only — no logic, no ORM.

```python
class PageController(TokenHasScopePermissionModelControllerMixin, ModelController):
    api = api_v1
    service = PageService
    path_prefix = "/website/pages/"
    auth = [OAuthTokenAuthentication()]
    permission_map = {"read": [...], "create": [...], "update": [...], "delete": [...]}

    list_response_schema: Schema = List[PageSchema]
    list_filter_schema: FilterSchema = PageFilterSchema
    list_ordering_fields = ["title", "slug"]      # direct model fields only
    list_ordering_default_fields = ["title"]
    retrieve_response_schema: Schema = PageSchema
    create_request_schema = PageCreateSchema
    create_response_schema = PageSchema
    update_request_schema = PageUpdateSchema
    update_response_schema = PageSchema
```

`ModelController` is all five CRUD mixins at once. Wanting fewer means composing
by hand — and the composition has import-time and security consequences covered
in `pitfalls.md`. Read that before choosing.

A resource with no model at all (a registry read out of code) subclasses
`BaseController`, declares no `service`, and carries its permissions on the route
rather than in `permission_map`, since there is no CRUD operation to map.
`HtmlWidgetController` is the example. `validate_controllers` skips a controller
whose `model` is `None`.

## Where each kind of rule lives

| Rule | Home | Why not elsewhere |
|---|---|---|
| Type, shape, required | schema | free, and before any query |
| `choices`, null, blank, field validators | nowhere — automatic | `to_internal_values` enforces every supplied value on both write paths |
| Relation exists and is visible | nowhere — automatic | resolved via the target service's `browse`, reported as `RelationNotFound` |
| Needs the current record | service `validate_data` | the only hook that receives the instance |
| Must hold on every write path | QuerySet override | services never call `save()`; the admin does |
| Derived values | QuerySet `bulk_create` | `validate_data` runs before the instance exists, `_create_postprocess` after the INSERT |
| Policy that would churn migrations | service | field `validators=[...]` change a field's deconstruction |

## Startup wiring

`core` is **last** in `INSTALLED_APPS` on purpose. `CoreConfig.ready()` runs, in
order: `autodiscover_modules('api')`, `('html_widget')`, `('services')`, then
`ServiceRegistry.validate()` and `validate_controllers()`.

Two things follow. A registry filled by an autodiscovery pass that runs *after*
`('api')` is empty while API schemas are being built — see the `choices` entry in
`pitfalls.md`. And because these checks run in `ready()`, they run for every
management command: a cross-layer inconsistency breaks `migrate` itself, not just
a test.

## App file layout

```
src/<app>/
  apps.py            AppConfig + populate_dependencies / populate_fixtures / populate_<env>()
  models/            one file per model, __init__.py star-imports
  schemas/           one file per resource (plural), __init__.py star-imports
  api/               one controller file per resource, __init__.py star-imports
  services.py        every service of the app, one module
  security.py        register_permission() calls + BaseRule classes
  admin.py           django admin
  urls.py / views/   only for apps with server-rendered pages
  jinja2/<app>/      jinja templates
  migrations/
  fixtures/{system,local}/
  tests/             test_models/ test_services/ test_api/ test_views/
```

Data provisioning is the custom `populate` management command, not migrations.
Apps opt in through `AppConfig.populate_dependencies`, `populate_fixtures`, and a
`populate_<env>()` method.
