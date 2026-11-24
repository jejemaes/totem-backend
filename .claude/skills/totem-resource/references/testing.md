# Testing conventions

## Table of contents

- [Layout](#layout)
- [Running](#running)
- [Service tests](#service-tests)
- [API tests](#api-tests)
- [The `assert_api_format` contract helper](#the-assert_api_format-contract-helper)
- [SSR view tests](#ssr-view-tests)
- [What deserves a test here](#what-deserves-a-test-here)

## Layout

One directory per layer, mirroring where the logic lives:

```
src/<app>/tests/
  test_models/     QuerySet overrides, constraints, defaults
  test_services/   validate_data, named reads, composition
  test_schemas/    field-level validation of the input schemas
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

Every app follows this convention. `src/user/tests/test_services/` is the
smallest reference; `src/account/tests/test_services/` shows a chain of
`common_*` mixins, group by, resequence and rules registered for the test
(`test_account_movement_group_by`); `src/authentication/tests/test_services/`
shows a service bound to no model (`AuthService`), one file per operation.

### Files, one set per resource

| File | Covers |
|---|---|
| `common_<resource>.py` | the data: a `<Resource>ServiceCommonMixin`, `setUpTestData` only |
| `test_<resource>.py` | create, read, update, delete, default values |
| `test_<resource>_display_name.py` | `display_name` |
| `test_<resource>_resequence.py` | `ResequenceMixin` |
| `test_<resource>_group_by.py` | `GroupByMixin` |
| `test_<resource>_<op>.py` | an operation of its own (`read_tree`, `upload`, `change_password`, `login`…) |

Schema tests do not belong here: they go in `<app>/tests/test_schemas/test_<resource>.py`
(a `SimpleTestCase`, asserting the field named by the pydantic error).

- `common_<resource>.py` holds data only: id constants at module level,
  `bulk_create`, Lord of the Rings names. One resource's mixin may extend
  another's (a budget line extends the budget).
- One `TestCase` per file:
  `class <Resource>ServiceTest(<Resource>ServiceCommonMixin, ServiceTestCaseMixin, TestCase)`,
  one `# ---` banner section per operation, a `# Utils` section at the bottom.
- `core.testing.ServiceTestCaseMixin.get_service(ServiceClass, user=...)` builds
  the service in a **fresh** `Environment`: an environment memoizes the roles of
  its user, so a service built before a role edit keeps the old rules.
  `user=None` is an anonymous caller or an API key: no role, so no rule.
- `core.testing.MediaRootTestMixin` gives the class a temporary `MEDIA_ROOT`.

### Every test asserts input and output

- What the service **returns** (instances, `(count, queryset)`, the count
  deleted) **and** what is **in the database** afterwards: the values written,
  the rows gone, the rows left untouched on a refusal.
- Its **query count**, `assertNumQueries`, as a parameter of the row when it
  varies. A count moving is what tells that a relation, a prefetch or a refresh
  changed; say in a comment what the queries are when it is not obvious.
- `@parameterized.expand` wherever two tests differ only by data, with a named
  label as first argument (`label`, never `dummy`).
- Errors: `ServiceValidationMultiError.dict()` is keyed by the payload **index**
  for what `to_internal_values` refuses (relations, field rules), by the record
  **pk** for `validate_data` during an update, and by `"__all__"` for a database
  constraint (`_database_error_to_validation_error`). Assert the key and the
  field named, not only that it raised.

### Which tests, per operation

- **create**: `test_create` (P), `test_create_invalid` (P), `test_create_refuses_a_dict`,
  `test_create_relations` (P, unknown or out-of-scope relation),
  `test_create_batch` (P, all or nothing, errors indexed), `test_default_values` (P),
  `test_create_access_rules` (P).
- **read**: `test_read_filters` (P, the pks), `test_read_ordering` (P),
  `test_read_fields` (P, what is loaded or deferred, what is prefetched),
  `test_read_access_rules` (P).
- **update**: `test_update` (P), `test_update_partial`, `test_update_invalid` (P),
  `test_update_refuses_a_dict`, `test_update_batch`, `test_update_not_found`,
  `test_update_access_rules` (P).
- **delete**: `test_delete` (P, cascades and `SET_NULL`), `test_delete_protected`
  (P, for a `PROTECT`), `test_delete_access_rules` (P).
- **display_name**: `test_display_name` (P, valid, unknown, malformed, repeated
  pks), `test_display_name_access_rules` (P).
- **resequence**: `test_resequence` (P, the order in the database),
  `test_resequence_invalid` (P), `test_resequence_access_rules` (P).
- **group_by**: `test_group_by_dimensions`, `_measures`, `_filters`, `_ordering`,
  `_pagination`, `_invalid`, `_access_rules`, all (P).
- **an operation left out on purpose**: `test_operation_is_not_composed` (P over
  the names), `assertFalse(hasattr(Service, name))`.
- **an operation of its own**: one section, `test_<op>_<behaviour>`, same
  requirements.

When a test from this list cannot exist, leave it out and say why in a comment
in its section.

### Access rules

Test **the rule, not a role**: never a role from the fixtures. Set the rules on
the role the acting user currently holds, as the API tests do:

```python
self.role.rules = rules
self.role.save()
service = self.get_service(UserService, user=self.user_frodon)  # after the edit
```

Rows: `[]`, one per rule, a combination (the rules of a role combine with AND),
two roles (roles combine with OR), and an anonymous row
(`get_service(Service)`, which no rule reaches). A rule whose `operations` do not
include the operation under test holds nothing back: pin it with a comment on
the row. Never mock `apply_access_rules`: register a real `BaseRule` for the test
if the project has none (see `user/tests/test_services/test_relation_resolution.py`).
No `BaseRule` for the model → no `*_access_rules` tests, and the class docstring
says so.

## API tests

`src/user/tests/test_api/` is the reference; `src/account/tests/test_api/` follows
it too, with nested routes, budget rules, resequence and group by. The other apps
still use an older
style (an `AccessTokenStub` holding every scope, `request` and payload helpers);
do not copy it, and migrate a module to this convention when you rewrite its
tests.

### Files, one set per resource

| File | When | Covers |
|---|---|---|
| `test_<resource>.py` | always | the CRUD mixins the controller composes |
| `test_<resource>_actions.py` | the controller declares extra `@route`s | one section per route |
| `test_<name>_actions.py` | a controller with no model, only `@route`s (`ThemeController`, `HtmlWidgetController`) | one section per route, no rules tests |
| `test_<resource>_display_name.py` | `DisplayNameModelControllerMixin` | `/display-name/` |
| `test_<resource>_resequence.py` | `ResequenceModelControllerMixin` | `/resequence/` |
| `test_<resource>_group_by.py` | `GroupByModelControllerMixin` | `/group-by/` |

Each file has one `TestCase` class, with one `# ---` banner section per
operation and a `# Utils` section at the bottom.

### The test class

```python
class ThingAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Thing.objects.bulk_create([...])
        cls.role.permissions = THING_SCOPES   # the whole resource, no rule
        cls.role.rules = []
        cls.role.save()
        cls.url = "/api/v1/things/"
        cls.url_detail = f"/api/v1/things/{THING_ID1}/"
```

- `CommonTestMixin` holds shared data only: there is one per module, in
  `<app>/tests/test_api/common.py`. `user.tests.test_api.common` provides Frodon
  and Gollum, `cls.role` and the API key; a module's own one extends it (see
  `account.tests.test_api.common`) and leaves the data of the service tests
  (`<app>/tests/common.py`) alone. `core.testing.APITestCaseMixin` is not modified.
- Put id constants at module level. Build records with `bulk_create` whenever
  the model allows it.
- Test data uses Lord of the Rings names: Frodon, Gollum, Pipin, Galadriel, Sam;
  "Fellowship of the Ring", "Mordor Orcs"…
- A payload is data, either a class attribute or an inline dict. Vary it with
  `{**self.payload_create, **extra}` and never `.update()`, which mutates the
  shared dict for the tests that follow.
- **The only two methods a test class defines are `do_request` and
  `assert_api_format`.** Do not add a `request` helper, a payload builder or a
  grant helper. Each class copies them on purpose: a file must read on its own.

```python
def do_request(self, method, url, auth="user", data=None, params=None):
    if auth == "apikey":
        return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
    token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
    return self.do_api_request(url, method, token, data=data, params=params or {})
```

The token is minted **on each call from the role's real permissions**, as the
login would. Granting a scope therefore means editing the role, never forging a
token. Minting reads the roles, which is one query: `assertNumQueries` counts it.

### Access rights and access rules

Never use a role from the fixtures (`USERTYPE_ADMIN`…) or a role created for the
occasion. Change the role the user **currently holds**:

```python
# access rights, user: parameterized over (permissions, status_code)
self.role.permissions = permissions
self.role.save()
# access rights, API key
self.api_key.scope = permissions
self.api_key.save()
# access rules, user: parameterized over (rules, expected_pks); permissions stay complete
self.role.rules = rules
self.role.save()
```

- Access-rights rows: `[]`, the required scope, the other scopes of the
  resource, and a scope of another resource. On a 403, also assert the body
  `{"detail": ["You do not have permission to perform this action."]}`.
- Access-rules tests assert **the pks that are reached**, not only the status:
  - list and display name: `{item["id"] for item in results} == set(expected_pks)`;
  - retrieve, update and delete: the status (out of reach is a 404), plus the
    database state (the row was written or deleted, or it was not);
  - create: the status, plus the created pk.
  Put one row per rule, plus `[]`, plus a combination: the rules of a role
  combine with AND, and roles combine with OR.
- `*_apikey_access_rules` tests **pin the bypass**. A key has no user, so it has
  no role and no rule applies to it (see `ApiKeyAuth`). Same rows as the user
  test, but the key always reaches everything.
- A rule whose `operations` do not include the operation under test **holds
  nothing back**. For example, `user_manage_own_profile` covers neither
  `create` nor `delete`. Pin it with a comment on the row.
- No `BaseRule` registered for the model → no `*_access_rules` tests. Explain
  the absence in the class docstring.

### Which tests, per mixin

`(P)` means `@parameterized.expand`. `user` = token, `apikey` = API key.

- **list**: `test_list_response`, `_filters` (P), `_invalid_filters` (P),
  `_ordering` (P), `_query_fields` (P), `_invalid_query_fields` (P),
  `_searching` (P), `_user_access_rights` (P), `_apikey_access_rights` (P),
  `_user_access_rules` (P), `_apikey_access_rules` (P).
- **retrieve**: `test_retrieve_response`, `_not_found`,
  `_user/_apikey_access_rights` (P), `_user/_apikey_access_rules` (P).
- **create**: `test_create_request_field_validation` (P), `_response`,
  `_user/_apikey_access_rights` (P), `_user/_apikey_access_rules` (P).
- **update**: `test_update_request_field_validation` (P), `_response`,
  `_user/_apikey_access_rights` (P), `_user/_apikey_access_rules` (P).
- **delete**: `test_delete_response`, `_user/_apikey_access_rights` (P),
  `_user/_apikey_access_rules` (P).
- **default_value**: `test_default_value_request`, `_response`,
  `_query_fields` (P), `_user/_apikey_access_rights` (P).
- **extra `@route`** (`_actions.py`), for each route `<name>`:
  `test_<name>_response`, `test_<name>_request` (P, if it has a body), and
  `_user/_apikey_access_rights` (P).
- **display_name** (`_display_name.py`): `test_display_name_request` (P, valid
  and invalid ids), `_response`, `_user/_apikey_access_rights` (P),
  `_user/_apikey_access_rules` (P).
- **resequence** (`_resequence.py`): `test_resequence_request` (P, valid and
  invalid), `_response`, `_user/_apikey_access_rights` (P),
  `_user/_apikey_access_rules` (P).
- **group_by** (`_group_by.py`): `test_group_by_request_group_by_fields` (P),
  `_request_measures` (P), `_request_filters` (P) — each with valid and invalid
  params; `test_group_by_response_group_by_fields`, `_response_measures`,
  `_response_filters` — each asserting format and values, with part of the
  expected response given by the parameters; `_response_ordering` (P),
  `_response_pagination` (P, assert the values returned),
  `_user/_apikey_access_rights` (P), `_user/_apikey_access_rules` (P).

When a test from this list cannot exist, leave it out and say why in a comment
in its section. For example, a filter schema made only of strings has no
invalid filter, and a route guarded only by `IsAuthenticated` always answers
200 to a user and 403 to a key.

**A controller mixin with no entry in this list** (a new mixin in
`core/api/controller.py`, or one applied for the first time to a resource): do
not invent its tests. Propose the list of tests, named on the pattern above
(`test_<op>_request`, `_response`, `_user/_apikey_access_rights`,
`_user/_apikey_access_rules`), and **ask the user which ones to write** before
writing them. Then add the entry here.

## The `assert_api_format` contract helper

Each API test class defines its own, in the `# Utils` section. It
checks each value against the ORM record **and** ends with:

```python
self.assertEqual(set(fields), set(api_data))
```

That last line is the point. Field-by-field assertions only see what they name,
so a field appearing in or vanishing from the response schema passes unnoticed;
this makes the response shape itself the contract. Duplicating the helper per
class is deliberate — each one encodes its own resource's shape, including how
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
