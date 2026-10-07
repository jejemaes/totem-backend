
# Totem Deployment

## How To Deploy Locally ?

Once you have checkout this repository with `git clone`, you can run the docker containers locally with

`docker compose up --build` (or without the `--build` option, to avoid buiding the docker image).

Then, to load local data to ease the development, use

`docker compose exec django ./manage.py populate` (See the `commands` section for more details).

This is done, you can go to `http://localhost:8000` to enjoy the public website, or on `http://localhost:8000/admin` to access the native django administration (login and password are `admin`).

When coding, python code is automatically reloaded. Jinja2 Template requires a container restart (maybe a build).


## Environment Variables

Here is a list of required environment variables to run the django container of the Totem Service. They are split in categories, usually prefixed by the component name. Only native django settings and totem business-related are prefixed by `TOTEM_`.

### Django

 - `TOTEM_DEBUG`: boolean, indicating if django should run in debug mode or not. Default is `False`.
 - `TOTEM_SECRET_KEY`: string, the django secret key.
  - `TOTEM_CSRF_TRUSTED_ORIGINS`: comma separated complete url of trusted origins. Django 4 required it. Example: `http://localhost:8104,https://mydomain.com:8104`


### Postgres

- `POSTGRES_NAME`: string, the name of the django database to use
- `POSTGRES_USER`: string, username to access the psql server
- `POSTGRES_PASSWORD`: string, user password to access the psql server
- `POSTGRES_HOST`: string, the URL of the psql server
- `POSTGRES_PORT`: string, the port of psql server

### Celery

- `CELERY_BROKER_URL`: string, the URL of the Redis broker. Default is `redis://redis:6379/0`.
- `TOTEM_LOG_LEVEL`: string, the level of the root logger. Default is `INFO`.


## Background Jobs

Background jobs run on Celery, with Redis as broker. Besides the web server, the same docker image runs two more processes:

- the worker, executing the tasks: `celery -A totem worker --loglevel info`. It can be scaled to several instances.
- the scheduler, sending the periodic tasks when due: `celery -A totem beat --loglevel info`. **Exactly one** instance must run, otherwise the periodic tasks are sent twice.

The schedules of the periodic tasks are stored in the database, and can be changed (or disabled) from the django admin, under *Periodic Tasks*, without restarting anything. The default ones are created by `./manage.py populate --env system`, which never overrides a schedule that already exists.

There is no result backend: the outcome of a task (success with its duration, or failure with its traceback) is only logged by the worker.
