
# Totem Useful Commands

All those commands are tools for developers or can be used as helpers in production environment (carefully of course). As they are django commands, some help can be found with

    docker-compose exec ./manage.py my_command --help

### Wait For Database

When starting the service, the database might not be ready to accept queries. Django will then crash. The command `wait_for_db` can be launched to make django wait before starting.

    docker-compose exec ./manage.py wait_for_db


### Tenant Migrate

Each tenant has its own database. `migrate` runs on the database of the settings (`POSTGRES_NAME`); to migrate another tenant database, give its name first. The other arguments and options are those of `migrate`.

    docker-compose exec django ./manage.py tenant_migrate tenant_acme

The database must already exist: this command creates no database.

### Filestore To Tenant Layout

Each tenant database has its own media root, `MEDIA_ROOT/<db_name>/{_filestore,public,private}`. To upgrade a deployment made before that, move its media under the root of its database, once, with the services stopped:

    docker-compose run --rm django ./manage.py filestore_to_tenant_layout postgres --dry-run
    docker-compose run --rm django ./manage.py filestore_to_tenant_layout postgres

The symlinks of the media stores are rewritten as relative ones. Nothing is changed in the database.

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
 - For OAuth App: `docker-compose exec django ./manage.py dumpdata oauth.OAuthApp -o oauth/fixtures/system/oauth_app.json --format json --indent 4`

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

