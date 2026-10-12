#!/bin/bash

set -e

python ./manage.py wait_for_db
# Every tenant database (the one of the settings, without a catalog), and the
# content types of the models removed since.
python ./manage.py tenant_migrate --all --noinput --remove-stale-contenttypes
# No `clearsessions`: beat clears the expired sessions of each tenant daily.
