import json
import urllib.parse as urlparse
from urllib.parse import urlencode

from django.core.management import call_command
from django.db import connection, connections
from django.test import Client

from core.db.tenancy import use_database


class APITestCaseMixin:

    def do_api_request(self, url, method, token, data=None, params={}, **headers):
        """Do a request to the given endpoint and return the django Response object corresponding.
        :param url: complete URL to call (hostname + path)
        :param method: either GET, POST, PATCH, PUT or DELETE.
        :param token: string containing the bearer token to place in auth header.
        :param data: dict of value to put in the request body
        :param params: GET parameters to add in the URL
        :param headers: any additionnal header. String like `X_HTTP_MY_STUFF`
        """
        auth = {"HTTP_AUTHORIZATION": "Bearer " + token}
        return self._do_request(url, method, auth, data=data, params=params, **headers)

    def _do_request(self, url, method, auth=None, data=None, params={}, content_type="application/json", **headers):
        # add GET params
        url_parts = list(urlparse.urlparse(url))
        query = dict(urlparse.parse_qsl(url_parts[4]))
        query.update(params)
        url_parts[4] = urlencode(query)

        url = urlparse.urlunparse(url_parts)  # /my-path/?param=value
        # do the request
        client = Client()
        if auth:
            headers.update(auth)

        if method == "POST":
            response = client.post(url, data, content_type=content_type, **headers)
        elif method == "GET":  # allow GET to have body
            response = client.generic(
                "GET",
                url,
                data=json.dumps(
                    data or {}
                ),
                content_type="application/json",
                **headers,
            )
        elif method == "PATCH":
            response = client.patch(url, data, content_type=content_type, **headers)
        elif method == "DELETE":
            response = client.delete(url, **headers)
        elif method == "PUT":
            response = client.put(url, "application/json", **headers)
        elif method == "OPTIONS":
            response = client.options(url, **headers)

        return response

class TenantDatabaseTestMixin:
    """ Gives a `TransactionTestCase` a second, migrated tenant database.

    Its name, `tenant_db`, derives from the test database, so that parallel
    test workers each get their own. It is created and migrated once per test
    class (a few seconds), then dropped.

    Not for a `TestCase`: its transaction on `default` forbids switching to
    another database (`DatabaseSwitchError`).
    """

    tenant_db_suffix = "tenant"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tenant_db = f"{connection.settings_dict['NAME']}_{cls.tenant_db_suffix}"
        with connection._nodb_cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{cls.tenant_db}"')
            cursor.execute(f'CREATE DATABASE "{cls.tenant_db}"')
        call_command("tenant_migrate", cls.tenant_db, verbosity=0)

    @classmethod
    def tearDownClass(cls):
        forget_database(cls.tenant_db)
        with connection._nodb_cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS "{cls.tenant_db}"')
        super().tearDownClass()

    def tearDown(self):
        # `TransactionTestCase` only flushes the databases of `databases`.
        with use_database(self.tenant_db):
            call_command("flush", interactive=False, verbosity=0)
        super().tearDown()


class ForgetDatabaseAliasesMixin:
    """ Forget, after each test, the database aliases it created.

    A request designating a database (`X-Tenant-Db`) creates its alias. Left
    behind, it breaks the teardown of the test case: Django removes its
    "queries not allowed" guards from every alias it iterates, but only put
    them on the aliases that existed when the test case started.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(self.forget_new_aliases, connections.tenant_aliases())

    def forget_new_aliases(self, known):
        for alias in connections.tenant_aliases() - known:
            forget_database(alias)


def forget_database(db_name):
    """ Close the alias of a database and remove it, so that it can be dropped. """
    connections.forget_database(db_name)
