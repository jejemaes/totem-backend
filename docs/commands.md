
# Totem Useful Commands

All those commands are tools for developers or can be used as helpers in production environment (carefully of course). As they are django commands, some help can be found with

    docker-compose exec ./manage.py my_command --help

### Wait For Database

When starting the service, the database might not be ready to accept queries. Django will then crash. The command `wait_for_db` can be launched to make django wait before starting.

    docker-compose exec ./manage.py wait_for_db


### Tenant Migrate

Each tenant has its own database. `migrate` runs on the database of the settings (`POSTGRES_NAME`); to migrate another tenant database, give its name first. The other arguments and options are those of `migrate`.

    docker-compose exec django ./manage.py tenant_migrate tenant_acme

The database must already exist: this command creates no database. With `--all` instead of a name, every active tenant is migrated in turn: those of the catalog (`saas_base`) when `SAAS_DB_NAME` is set, otherwise the database of the settings. `--remove-stale-contenttypes` then deletes the content types of the removed models, without prompting.

    docker-compose exec django ./manage.py tenant_migrate --all

### Filestore To Tenant Layout

Each tenant database has its own media root, `MEDIA_ROOT/<db_name>/{_filestore,public,private}`. To upgrade a deployment made before that, move its media under the root of its database, once, with the services stopped:

    docker-compose run --rm django ./manage.py filestore_to_tenant_layout postgres --dry-run
    docker-compose run --rm django ./manage.py filestore_to_tenant_layout postgres

The symlinks of the media stores are rewritten as relative ones. Nothing is changed in the database.

### Authentication

The API is reached with one of two credentials, and both are obtained outside of a fixture.

A **user** exchanges a login and a password for a pair of tokens:

    curl -s -X POST localhost:8000/api/v1/auth/token/ -H 'Content-Type: application/json' -d '{"username":"admin","password":"totem"}'

`totem` is the password `populate --env local` sets on every user of the local dataset; the hash shipped in the fixture has no known clear text, so it is that command, not the fixture, that makes logging in possible. The response carries an `access_token` valid 15 minutes, used as `Authorization: Bearer <token>`, and a `refresh_token` valid 14 days, exchanged on `/api/v1/auth/token/refresh/` for a fresh pair. Rotation is single-use: the old refresh token dies with the exchange, and replaying it revokes the whole session. `/api/v1/auth/token/revoke/` ends a session early.

To skip the exchange, or to get a token that outlives a debugging session:

    docker-compose exec django ./manage.py mint_token admin --ttl-days 30

The token is printed on stdout and its details on stderr, so `$(... 2>/dev/null)` captures just the token. Scopes default to everything the user's roles grant; `--scopes a,b` narrows them, which is how a 403 is reproduced. A `--ttl-days` above 1 requires `DEBUG`, because an access token is never looked up and therefore cannot be revoked. The token carries the name of the database it was minted on and is rejected by every other tenant.

A **machine** uses an API key, sent as `X-Api-Key`:

    docker-compose exec django ./manage.py create_api_key "Nightly Export" --scopes totem.contact.read,totem.website.read

The secret is printed once and only its hash is kept — there is no fixture for a key, since that would be a credential in the repository. `populate --env local` does create one named `Local Development`, secret `dev-api-key-secret`, **with no scopes**: it makes the header path reachable, not useful. Keys hold public permissions only, so no key can create keys.

Note what a key does *not* get: row-level access rules are built from the roles of a user, and a key has no user, so a key holding `totem.user.read` reads every user of the tenant. That is intended for a machine caller, and it is why keys are granted narrowly.


### Populate

This command imports data for the specified environment. This command is idempotent

    docker-compose exec django ./manage.py populate --env local --size small --drop-db

 - `--env`:  required env corresponding to the dataset to load. Either `system`, or `local` will load the data required for the service to run.
 - `--drop-db`: optional. If set, will erase the database (schema and data). Then migration scripts will be re-executed before populating.
 - `--size`:  optional size of the set of data to introduce in database. Either `small`, `medium` or `large`. Default is `small`.
 - `--db-name`: optional tenant database to populate. Default is the database of the settings (`POSTGRES_NAME`).

The command will load authorized fixtures, and execute code to generate or alter data to fit the environment.


### Fixture Data

To load data for a specific env, use the `populate` command. It will generate data for the system *and* for the chosen environment. For instance,
    `docker-compose exec django ./manage.py populate --env local`
will create the system data (required for the system to work), and fake data for the developper to code locally.


To save data from a django app, the `dumpdata` should be used. Be careful, we distingush data for `local` dev and `system` data required for the application to run.

#### System Data

System Data are created with:
 - For User Roles: `docker-compose exec django ./manage.py dumpdata user.UserRole -o user/fixtures/system/user_role.json --format json --indent 4`
 - For Website: `docker-compose exec django ./manage.py dumpdata website.Website -o website/fixtures/system/website.json --format json --indent 4`

#### Local Data

Local Data can be generated with a few commands:
 - For User: `docker-compose exec django ./manage.py dumpdata user.User -o user/fixtures/local/user.json --format json --indent 4`
 - For Website Page: `docker-compose exec django ./manage.py dumpdata website.Page -o website/fixtures/local/page.json --format json --indent 4`
 - For Website Menu: `docker-compose exec django ./manage.py dumpdata website.Menu -o website/fixtures/local/menu.json --format json --indent 4`

### Tests

To run the test suite, use

    docker compose exec django ./manage.py test --parallel --settings=totem.tests.settings

Specific test case can be specified with dot-notation like

    docker compose exec django ./manage.py test user.tests.test_api --parallel --settings=totem.tests.settings

