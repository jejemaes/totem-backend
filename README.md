# totem

[![Tests](https://github.com/jejemaes/totem-backend/actions/workflows/tests.yml/badge.svg)](https://github.com/jejemaes/totem-backend/actions/workflows/tests.yml)

Backend for website and API of a plateform to manage scout groups.

### Tests

To run the test suite, use

    docker compose exec django ./manage.py test --parallel

Specific test case can be specified with dot-notation like

    docker compose exec django ./manage.py test user.tests.test_api --parallel

### Populate

This command imports data for the specified environment. This command is idempotent

    docker-compose exec django ./manage.py populate --env local --size small --drop-db

 - `--env`:  required env corresponding to the dataset to load. Either `system`, `local` or `staging`. `system` will load the data required for the service to run.
 - `--drop-db`: optional. If set, will erase the database (schema and data). Then migration scripts will be re-executed before populating.
 - `--size`:  optional size of the set of data to introduce in database. Either `small`, `medium` or `large`. Default is `small`.

The command will load authorized fixtures, and execute code to generate or alter data to fit the environment.


### Fixture Data

To save data from a django app, the `dumpdata` should be used. Be careful, we distingush data for `local` dev and `system` data required for the application to run.

 - For user role: `docker compose exec django ./manage.py dumpdata user.UserRole -o user/fixtures/local/user_role.json --format json --indent 4`



