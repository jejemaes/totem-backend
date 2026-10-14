# SaaS Operation

Each tenant has its own database (see `core/db/tenancy.py`). The `saas` app holds what the operator of the platform needs to run them.

### Create a tenant

Both endpoints act on the database **the domain of the request designates**: the proxy resolves the domain to the database of the tenant and forwards it in the `X-Tenant-Db` header. They only exist when `SAAS_API_KEY` is set, and require that key in the `X-Api-Key` header.

`POST /saas/tenant-create/` creates the database of a new tenant, migrates it, loads its system data (`populate --env system`), creates its administrator and names its website. The proxy declares the tenant and its domain first, then calls this endpoint on that domain.

    curl -X POST https://acme.example.com/saas/tenant-create/ \
        -H "X-Api-Key: $SAAS_API_KEY" -H "Content-Type: application/json" \
        -d '{"email": "admin@acme.com", "name": "ACME", "password": "..."}'

| Field      | Content                                                                     |
| ---------- | --------------------------------------------------------------------------- |
| `email`    | Email of the administrator, also their login                                 |
| `name`     | Name of the tenant, given to its website                                     |
| `password` | Password of the administrator, checked by the password validators            |

| Status | Meaning                                                              |
| ------ | -------------------------------------------------------------------- |
| 201    | Created                                                              |
| 400    | No tenant designated: the request did not come through the proxy     |
| 422    | Invalid body: `detail` lists the errors, `loc` naming the field      |
| 401    | Missing or wrong API key                                             |
| 404    | `SAAS_API_KEY` is not set, or `X-Tenant-Db` is not a database name   |
| 409    | A database of that name already exists                               |
| 500    | A step failed: the database is dropped, the call can be made again   |

The request takes a few seconds; nginx gives it 3 minutes. The tenant still has to be declared in the catalog (`saas_base`) and given a domain at the proxy before it can be reached.

### Migrate a tenant

`POST /saas/tenant-migrate/` applies the pending migrations to the database of the tenant of the domain, then loads its system data (`populate --env system`: the system fixtures, reset to their values, and the periodic tasks). Without the header (a single-tenant deployment, without a proxy), it migrates the database of the settings.

    curl -X POST https://acme.example.com/saas/tenant-migrate/ \
        -H "X-Api-Key: $SAAS_API_KEY" -H "Content-Type: application/json" \
        -d '{"kill_connections": false}'

    {"dbname": "tenant_acme", "killed_connections": 0, "applied": ["website.0007_..."]}

By default the migration runs **hot**, while the tenant serves. That is safe when the migrations are backward compatible with the code still running: add first, and only drop or rename once the new code is deployed everywhere; give a new `NOT NULL` column a `db_default`; build the indexes of a large table with `AddIndexConcurrently`. A migration waits 5 seconds at most for a lock, then gives up (409): waiting longer would freeze every query on that table behind it.

With `"kill_connections": true`, every session open on the database is terminated first (requests and tasks in progress fail). It is meant for a migration that must not run alongside the code, once the proxy has taken the tenant offline (it keeps this endpoint reachable). The pools of the other processes check a connection before handing it out (`CONN_HEALTH_CHECKS`), so they recover from the terminated sessions.

| Status | Meaning                                                               |
| ------ | --------------------------------------------------------------------- |
| 200    | Migrated: `applied` lists the migrations applied, empty if none       |
| 401    | Missing or wrong API key                                              |
| 404    | No such database, or `SAAS_API_KEY` is not set                        |
| 409    | A migration waited too long for a lock: retry                         |
| 422    | Invalid body                                                          |
| 500    | A migration or the system data failed: the migrations before it stay applied |

To migrate every tenant from a shell, see `tenant_migrate --all` in [commands](commands.md).
