# Testing conventions

## Table of contents

- [Layout](#layout)
- [Running](#running)
- [Service tests](#service-tests)
- [API tests](#api-tests)
- [The `_assert_api_format` contract helper](#the-_assert_api_format-contract-helper)
- [SSR view tests](#ssr-view-tests)
- [What deserves a test here](#what-deserves-a-test-here)

## Layout

One directory per layer, mirroring where the logic lives:

```
src/<app>/tests/
  test_models/     QuerySet overrides, constraints, defaults
  test_services/   validate_data, named reads, composition
  test_api/        status codes, response shape, scopes
  test_views/      server-rendered pages (website only)
```

A rule tested at the wrong layer usually means it is *implemented* at the wrong
layer — worth a second look before writing the test.

## Running

```bash
docker compose up -d db
docker compose run --rm --no-deps --entrypoint "" django python manage.py test
```

There is no usable local virtualenv. Narrow with a dotted path:
`... python manage.py test website.tests.test_api.test_website`.

Run the **whole** suite for any change under `src/core/`: that layer is on every
app's write path, and a change there fails in apps you were not thinking about.
Get a baseline count first (`git stash`) so you can tell your failures from
pre-existing ones.

## Service tests

```python
class TestPageService(TestCase):
    def setUp(self):
        super().setUp()
        self.env = Environment(None)
        self.service = self.env.get(PageService)
```

`Environment(None)` is an anonymous visitor; pass a user to exercise access
rules. Call the async surface through `async_to_sync(self.service.create)([schema])`.
Assert on `ServiceValidationMultiError`, and check *which key* carries the error:

```python
with self.assertRaises(ServiceValidationMultiError) as ctx:
    ...
self.assertIn("homepage", ctx.exception.dict()[0])
```

Errors from `to_internal_values` are keyed by the payload's **index** (`0`),
because they are raised before any row is matched. Errors from `validate_data`
during an update are keyed by the record's **pk**. Getting this wrong produces a
confusing `KeyError` rather than a failed assertion.

## API tests

Follow `src/user/tests/test_api/test_user.py` — it is the reference:

```python
class ThingAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.url = "/api/v1/things/"
        cls.url_detail = f"/api/v1/things/{THING_ID}/"
        cls.payload_update = {...}
```

- Module-level id constants; `url` / `url_detail` and shared payloads in
  `setUpTestData`.
- `CommonTestMixin` (from `user.tests.test_api.common`) provides users, an OAuth
  app and access tokens. Set the scope under test with
  `cls.user_access_token_frodon.scope = ...; save(update_fields=["scope"])`.
- `self.do_api_request(url, method, token, data=...)` — `data` may be a dict.
- One section per operation, with a `# ---` banner. Permission tests named
  `test_<op>_access_rights`, parameterized over `(scope, status_code)`.
- No token at all needs Django's bare `Client()`: `do_api_request` always builds
  an auth header.

## The `_assert_api_format` contract helper

Each API test module defines its own, in a `# Utils` section at the bottom. It
checks each value against the ORM record **and** ends with:

```python
self.assertEqual(set(fields), set(api_data.keys()))
```

That last line is the point. Field-by-field assertions only see what they name,
so a field appearing in or vanishing from the response schema passes unnoticed;
this makes the response shape itself the contract. Duplicating the helper per
module is deliberate — each one encodes its own resource's shape, including how
its relations serialize.

Cover the relations-unset case too, not just the populated one: it is what a
freshly provisioned record looks like, and the branch asserting `null` with the
**keys still present** is easy to leave untested.

## SSR view tests

Use `WebsiteViewTestMixin` (`website/tests/test_views/common.py`).
`get_unrendered_response(...)` returns the `TemplateResponse` before rendering,
which is what makes "which queries happen at render time" assertable:

```python
with self.assertNumQueries(0):
    response.render()
```

Two traps live here — see `pitfalls.md` 7 and 8. In short: never let a queryset
into the context, and never use `assertTemplateUsed` (it silently tests nothing
under jinja — assert on `response.template_name` instead).

`assertNumQueries` on the whole public request is worth pinning where a design
decision depends on it. `assertNumQueries(3)` on a page view is what would catch
a `BaseRule` being registered for a model the anonymous site reads, or the access
machinery starting to query for anonymous callers.

## What deserves a test here

Beyond the obvious happy path and permissions:

- **Absence as a contract.** When "you cannot create this" is expressed by not
  composing a mixin, assert it (`assertFalse(hasattr(Service, "create"))`) and
  assert the HTTP surface (405 / 404). Nothing else stops a well-meaning
  refactor.
- **Degradation paths.** Where the code chooses to degrade rather than raise —
  a missing record, a broken widget marker, an unpopulated database — the test
  is the only statement that this was intended.
- **The reason, not just the status.** Several unrelated mechanisms produce a
  422 here (the null check in `to_internal_values`, scoped relation resolution,
  `HtmlField` refusing an unknown widget). A row asserting only the code keeps
  passing when it starts failing for a different reason, so assert the field the
  error names:

  ```python
  self.assertEqual(
      [detail["loc"][-1] for detail in response.json()["detail"]], ["name"]
  )
  ```
