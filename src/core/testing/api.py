import json
import urllib.parse as urlparse
from urllib.parse import urlencode

from django.test import Client


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

    def do_api_key_request(self, url, method, api_key, data=None, params={}, **headers):
        """ The same request, authenticated as a machine caller.

        Its own helper rather than a flag on `do_api_request`: the two credentials
        go in different headers and give `request.auth` different shapes, and a
        test should say at the call site which of the two it exercises.
        """
        auth = {"HTTP_X_API_KEY": api_key}
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
