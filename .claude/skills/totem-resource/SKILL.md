---
name: totem-resource
description: How to add or change a REST resource in this totem-backend Django project — the model/service/schema/controller layering, the order to build it in, and the traps in core/ that are not discoverable by reading the happy path. Use this whenever work touches src/*/models/, services.py, schemas/, api/, security.py, or the tests under src/*/tests/ — including "add an endpoint", "expose X through the API", "add a field to Y", "why is this 422", "write tests for this controller", or any new Django app in this repo. Also use it before editing anything under src/core/, since the framework layer there has several load-bearing behaviours that look like bugs until you know why they exist.
---

# Adding a resource to totem-backend

This project puts a custom service/controller layer over Django 5 + django-ninja.
The layering is strict, and most of the mistakes worth avoiding come from
guessing which layer a rule belongs in. Read `references/architecture.md` for the
layer contract before writing anything, and `references/pitfalls.md` before
touching `src/core/` or composing a controller — that one is a list of
behaviours that will cost you a debugging session each if you meet them cold.

## The layers, in one pass

Request → **controller** (routes, scopes, response shape) → **service** (the only
place that reads or writes) → **QuerySet** (invariants that must hold on every
write path) → model.

Two rules explain most of the code you will read:

- **Nothing outside a service touches the ORM.** Views and controllers ask a
  service; the service applies access rules. A queryset handed out by a service
  already carries its rules as `Q` objects, so a caller may narrow it but never
  widen it.
- **Services write with `bulk_create()` and `queryset.update()`, never
  `save()`.** So anything that must happen on every write goes on the QuerySet,
  not in `save()` — that is why `PageQuerySet.update` stamps `update_date` and
  `MediaQuerySet.bulk_create` derives `checksum`/`mimetype`/`name`.

## Build order

Each step compiles and tests on its own, and the order is not arbitrary: schemas
import from models, services from schemas, controllers from services, and
`core.apps.CoreConfig.ready()` validates services against controllers at every
startup — so a half-applied change fails `ready()` (and therefore *every*
management command) rather than one test.

1. **Model** — `src/<app>/models/<name>.py`, one file per model, star-imported by
   `models/__init__.py`. `id = fields.ULIDField("ID", primary_key=True)`. Verbose
   name as the first positional argument on every field, `help_text` liberally.
   Put invariants on a custom QuerySet, not in `save()`.
2. **Migration** — `python manage.py makemigrations <app>`. Prefer non-null with a
   default so no data step is needed.
3. **Schemas** — `src/<app>/schemas/<plural>.py`: a `*DisplayNameSchema` (what a
   relation serializes to), a read `*Schema`, `*CreateSchema`, `*UpdateSchema`,
   `*FilterSchema`. Star-import from `schemas/__init__.py`. Annotate every
   relation explicitly (`user: Optional[UserDisplayNameSchema] = None`) — without
   it the relation serializes to a bare pk *and* is not prefetched.
4. **Service** — in the app's single `services.py`. Compose only the operations
   the resource really has; the absence of a mixin is how "this cannot be
   created/deleted" is expressed, so say why in the docstring.
5. **Security** — `src/<app>/security.py`: `register_permission("totem.<app><model>.<op>", ...)`
   per operation, plus any `BaseRule`. Grant the scopes in
   `src/<app>/fixtures/system/*.json` and `src/user/fixtures/system/user_role.json`
   — a scope granted to no role is an endpoint nobody can reach.
6. **Controller** — `src/<app>/api/<plural>.py`, star-imported from
   `api/__init__.py`. Read the composition rules in `references/pitfalls.md`
   first: inheriting `ModelController` when you do not want all five operations
   is the single most expensive mistake available here.
7. **Admin / fixtures** — `admin.py`, and `<app>/fixtures/{system,local}/`. The
   admin writes through `Model.save()`, so a rule enforced only in a service is
   bypassed there; if both writers matter, both need it.
8. **Tests** — see `references/testing.md`.

## Validation belongs in exactly one of three places

Choosing wrong is the most common review comment on this codebase.

- **Schema** — shape and type. Free.
- **Service `validate_data(data, instance)`** — business rules that need current
  state. It is the only hook that sees the record being written. `instance` is
  `None` on creation.
- **QuerySet override** — invariants that must hold however the write arrives,
  including from the admin and from a future caller.

A field-level rule (`choices`, null, blank, `validators=[...]`) needs no hook at
all: `ServiceBase.to_internal_values` enforces it on every supplied value, on
both write paths. And a relation needs no hook either — it is resolved through
the target service's `browse`, so it is already access-checked and reported as
`RelationNotFound`.

## Commits

`[ADD|IMP|FIX|REF] <app>: <lowercase summary>`. The body explains *why*, and
names the alternative that was rejected — that is the house style, in commits and
in comments alike. When you write a non-obvious line, write the reason next to
it; when you leave something out, say so and why. A reviewer here should never
have to ask "why not the obvious thing instead".

## Running things

Tests run in Docker; there is no usable local virtualenv.

```bash
docker compose up -d db
docker compose run --rm --no-deps --entrypoint "" django python manage.py test
```

Narrow it with a dotted path: `... python manage.py test website.tests.test_api.test_website`.
`python manage.py check` is a fast smoke test that the whole app registry,
service registry and controller set still validate at import.

## Reference files

- `references/architecture.md` — the layer contract in detail: `Environment`,
  access rules, the read/write surfaces, and where each kind of rule lives.
- `references/pitfalls.md` — **read before touching `src/core/` or composing a
  controller.** Verified, non-obvious behaviours: the unscoped-DELETE trap,
  import-time route collisions, `choices` evaluated too early,
  `ForeignKey.validate()` bypassing access rules, converters that silently
  cover nothing, and async-safety in the SSR views.
- `references/testing.md` — test layout, the `_assert_api_format` contract
  helper, permission tests, and the jinja trap that makes `assertTemplateUsed`
  silently useless.
