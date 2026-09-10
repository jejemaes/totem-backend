# Verified traps in `src/core/`

Every entry below was confirmed against this repository and its installed
Django 5.0.10 / django-ninja 1.4.5, not inferred from the docs. Each one is
something that looks like a bug — or like nothing at all — until you know why it
is there. Line numbers drift; the mechanism is the durable part.

## Table of contents

- [1. `ModelController` always registers DELETE, unscoped](#1)
- [2. Inheriting a CRUD mixin whose route you don't register breaks the import](#2)
- [3. `models.JSONField` in a schema — fixed, and the shape of bug to watch for](#3)
- [4. `choices` becomes a pydantic Enum at schema-creation time](#4)
- [5. `ForeignKey.validate()` queries unscoped](#5)
- [6. `full_clean()` before `bulk_create` validates an incomplete instance](#6)
- [7. Querysets must never reach a template](#7)
- [8. `assertTemplateUsed` is silently useless](#8)
- [9. Route order comes from `cls.__dict__` insertion order](#9)

## 1

**`ModelController` always registers DELETE, and leaves it unscoped.**

`DeleteModelControllerMixin.add_routes_to` is gated on `if cls.model:` **alone** —
every other CRUD mixin also checks for its schema (`if cls.model and
cls.retrieve_response_schema:`). So inheriting it registers `DELETE /{id}/`
whether you meant to or not. And `_get_action_permissions` returns `[]` for a key
absent from `permission_map`, so the route ends up requiring *no scope*: any
authenticated token can delete.

**Do this** when you do not want all five operations — compose explicitly, as
`MediaController` and `WebsiteController` do:

```python
class WebsiteController(
    TokenHasScopePermissionModelControllerMixin,
    RetrieveModelControllerMixin,
    UpdateModelControllerMixin,
    BaseModelController,          # not ModelController
):
```

And pin the resulting surface with a test — a later "let's just use
`ModelController` for symmetry" is exactly the change that must fail loudly.
Note the two status codes differ and both are correct: `DELETE /{id}/` answers
**405** (the path exists for GET and PATCH), while an unrouted collection path
answers **404** (nothing is registered, so django never reaches a view).

## 2

**Inheriting a CRUD mixin whose route you don't register raises `ValueError` at
import time.**

`BaseController.add_routes_to` sorts view members with
`list(cls.__dict__).index(name)`. A mixin's `update`/`retrieve` is a *shared
function object*, and it only lands in *your* class's `__dict__` when its route
is registered — registration goes through `method_to_route_function`, whose
`view_wrapper` branch does `setattr(cls, view_func.__name__, view_func)`. Skip
the registration and the sort raises `ValueError: 'update' is not in list`,
because another app's controller already stamped `MAGIC_ROUTE_ATTR` on that same
function object.

Consequence: dropping `retrieve_response_schema` from a controller does not
merely remove a route, it breaks the import. Inherit a mixin only if you also
declare its schema.

## 3

**`models.JSONField` in a `ModelSchema` — fixed, and worth knowing why.**

Historical: `core/schemas/fields.py` registered its JSON converter on
`django.contrib.postgres.fields.JSONField`, filed with the postgres contrib
fields. But that class survives in django 5 for historical migrations only (it
carries `system_check_removed_details`, so a model declaring it fails
`fields.E904`), and it is a *subclass* of `models.JSONField` — the field every
model actually declares. `singledispatch` resolves on the MRO, so the real field
fell through to the unregistered base and raised `ImproperlyConfigured` **while
the schema class was being built**, i.e. at import: listing a JSONField in
`Meta.fields` took the whole app down rather than one request.

Now registered on `models.JSONField`, which covers the contrib subclass through
the MRO. **A JSONField goes in `Meta.fields` like any other field.** It converts
to `AnyObject` (`{"type": "object"}`), deliberately not `t.Dict`: a JSON column
holds any json value and pydantic must not coerce or reorder what django stores
verbatim. Declare the field by hand only when you want a *narrower* shape
enforced than "some object".

The reason this entry survives the fix: it is the clearest example of the shape
of bug this converter module invites. A converter registered on a subclass, or
on an alias, silently covers nothing — and the failure lands at import time, in
whatever app happens to build a schema first. If you add a converter, register
the class models actually declare, and check whether a parent registration would
have covered it already.

## 4

**`choices` is turned into a pydantic `Enum` when the schema class is created —
not when a request arrives.**

`core/schemas/fields.py` does `if field.choices:` and builds an `Enum`. A
`CallableChoiceIterator` is always truthy, so a *callable* `choices` is evaluated
during `autodiscover_modules('api')` in `CoreConfig.ready()`.

So a callable reading a **static module constant** is fine, and gives you a real
enum in the OpenAPI schema plus an admin dropdown for free — and serializes into
migrations as an import reference, so adding a value generates no migration.

But a callable reading a **registry filled by a later autodiscovery pass**
(`('html_widget')`, or any pass you add after `('api')`) sees an empty registry:
you get an empty `Enum`, every write 422s, and every read of a stored value fails
serialization. For that case use a bare `CharField` and validate in the service.
`UserRoleSchema.permissions` is a latent instance of this — it works only because
controllers happen to import `user.security` first. Don't add a second.

Also note `choices` alone enforces nothing on the write path: Django applies it
in `Field.validate()`, reachable only through `full_clean()`. What actually
enforces it here is `to_internal_values` (see 5 and 6).

## 5

**`ForeignKey.validate()` looks the related row up through `_base_manager` — no
access rule narrows it.**

This is why `ServiceBase.to_internal_values` calls `field.validate(val, None)`
only `if not field.is_relation`. Running it on a relation would answer "exists"
for a record the acting user cannot see, contradicting the scoped resolution a
few lines below that reports `RelationNotFound` — and would duplicate its query.

`model_instance=None` is safe for non-relational fields: the base
`Field.validate()` never touches that argument, and the subclasses that do are
exactly the relational ones excluded.

## 6

**Do not call `instance.full_clean()` before `bulk_create`.**

Tempting, because no write path calls `full_clean()` and so `choices`/null/blank
are otherwise unenforced. But this codebase deliberately derives values *inside*
`QuerySet.bulk_create` — `MediaQuerySet` fills `checksum`, `mimetype` and `name`
there, and `User.password` is likewise set later. At the point instances exist,
they are intentionally incomplete, so cleaning them reports every derived field
as blank: an error about a field the caller was never meant to send. Trying it
turns ~40 green tests red.

The rules are instead enforced per *supplied value* in `to_internal_values`,
which both write paths pass through — so one place covers create and update, and
nothing fights the QuerySet convention. Note also that `full_clean()` does **not**
skip non-editable fields (`_get_validation_exclusions` belongs to `ModelForm`,
not to this path); it is `Field.validate()` that returns early on them.

## 7

**A queryset in a render context is a database query in the middle of a template
render.**

The SSR views are async, and the template renders outside any `sync_to_async`
hop — so a lazy value handed to it queries the database mid-render, past the
service layer and past its access rules. `RenderContextMixin.check_render_context_data`
raises `TypeError` on any `QuerySet` or `Manager` in the context. Materialize in
the view. `src/website/tests/test_views/test_async_safety.py` renders responses
explicitly to catch the rest.

Same reason widgets do all their reading in `get_render_context` (async, through
services) and never in their template.

## 8

**`assertTemplateUsed` passes no judgement at all in this project — it just
fails.**

It patches `django.template.base.Template._render`, which no jinja render goes
through. Verified: on a real page response, `response.templates` is `[]` and
`assertTemplateUsed` fails with "No templates used to render the response", while
`response.template_name` correctly holds `['website/page.html']`.

**Do this** — assert on `response.template_name` (the candidate list
`get_template_names()` returned), and pair it with `assertContains` on a string
unique to the template that actually rendered.

## 9

**Hand-written routes win path matching over generated ones, because of
`__dict__` insertion order.**

`BaseController.add_routes_to` sorts by `list(cls.__dict__).index(name)`. Methods
written in the class body are in `__dict__` from class creation; mixin-generated
ones are `setattr`'d later, during `add_routes_to`. So a hand-written
`/current/` or `/me/` is registered *before* `/{id}/` and matches first.

This is load-bearing rather than incidental: if it inverted, `GET /current/`
would be served by `retrieve` with `id="current"` and answer 404. Worth its own
test whenever you add such an alias.
