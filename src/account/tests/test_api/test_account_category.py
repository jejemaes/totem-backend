from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountCategory, AccountMovement
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    ACCOUNT_ID3,
    CATEGORY_BREE_ID,
    CATEGORY_GENERAL_ID,
    CATEGORY_SCOPES,
    CATEGORY_SHIRE_ID,
    MOVEMENT_ID3,
    PERMISSION_DENIED,
    CommonTestMixin,
)

CATEGORY_ID4 = "01JC0000000000000000000099"  # matches no category

ALL_CATEGORY_IDS = [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID, CATEGORY_BREE_ID]

CATEGORY_FIELDS = ["id", "name", "color", "account"]


@freeze_time("2026-10-15 11:12:13")
class AccountCategoryAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ No `*_access_rules` tests: no `BaseRule` is registered for `AccountCategory`,
    so whoever holds a scope reaches every category. """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.role.permissions = CATEGORY_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/categories/"
        cls.url_detail = f"/api/v1/accounting/categories/{CATEGORY_SHIRE_ID}/"
        cls.url_detail_general = f"/api/v1/accounting/categories/{CATEGORY_GENERAL_ID}/"
        cls.payload_create = {
            "name": "Lembas",
            "color": 4,
            "account": ACCOUNT_ID1,
        }
        cls.payload_update = {
            "name": "Old Toby",
            "color": 7,
        }

    # ------------------------------------------
    # List Operation
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data), {"count", "results", "next", "previous"})
        self.assertEqual(data["count"], len(ALL_CATEGORY_IDS))
        self.assertEqual({item["id"] for item in data["results"]}, set(ALL_CATEGORY_IDS))

        for item in data["results"]:
            self.assert_api_format(item, AccountCategory.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"account": ACCOUNT_ID1}, [CATEGORY_SHIRE_ID]),
            ({"account": ACCOUNT_ID3}, []),
            # What a movement of the account may use: the general ones and its own.
            ({"applicable_to": ACCOUNT_ID1}, [CATEGORY_GENERAL_ID, CATEGORY_SHIRE_ID]),
            ({"applicable_to": ACCOUNT_ID2}, [CATEGORY_GENERAL_ID, CATEGORY_BREE_ID]),
            ({"applicable_to": ACCOUNT_ID3}, [CATEGORY_GENERAL_ID]),
        ]
    )
    def test_list_filters(self, filters, expected_pks):
        response = self.do_request("GET", self.url, params=filters)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, AccountCategory.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ({"account": "not-a-ulid"}, "account"),
            ({"applicable_to": "not-a-ulid"}, "applicable_to"),
        ]
    )
    def test_list_invalid_filters(self, filters, error_field):
        response = self.do_request("GET", self.url, params=filters)

        self.assertEqual(response.status_code, 422)
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    @parameterized.expand(
        [
            ([], ["name", "id"]),  # default
            (["name"], ["name", "id"]),
            (["-name"], ["-name", "id"]),
            (["color"], ["color", "id"]),
            (["-color"], ["-color", "id"]),
        ]
    )
    def test_list_ordering(self, ordering_fields, order_by):
        params = {"ordering": ",".join(ordering_fields)} if ordering_fields else {}

        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(pk) for pk in AccountCategory.objects.order_by(*order_by).values_list("pk", flat=True)],
        )

    # The query counts include the one minting the token reads the roles with.
    @parameterized.expand(
        [
            ([], CATEGORY_FIELDS, 6),  # default means all fields
            (["name"], ["id", "name"], 5),  # `id` is always returned
            (["account"], ["id", "account"], 6),  # the relation costs its prefetch
        ]
    )
    def test_list_query_fields(self, query_fields, received_fields, query_count):
        params = {"fields": ",".join(query_fields)} if query_fields else {}

        with self.assertNumQueries(query_count):
            response = self.do_request("GET", self.url, params=params)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(ALL_CATEGORY_IDS))
        for item in data["results"]:
            self.assert_api_format(item, AccountCategory.objects.get(pk=item["id"]), received_fields)

    @parameterized.expand(
        [
            (["not_existing_field"],),
            (["not_existing_field", "account"],),  # with a relation
            (["not_existing_field", "name"],),
            (["movements"],),  # a reverse relation the schema does not publish
        ]
    )
    def test_list_invalid_query_fields(self, query_fields):
        response = self.do_request("GET", self.url, params={"fields": ",".join(query_fields)})

        self.assertEqual(response.status_code, 422)

    @parameterized.expand(
        [
            ("BREAKFAST", [CATEGORY_GENERAL_ID]),  # case insensitive
            ("ale", [CATEGORY_BREE_ID]),
            ("e", ALL_CATEGORY_IDS),
            ("mordor", []),
        ]
    )
    def test_list_searching(self, search_term, expected_pks):
        response = self.do_request("GET", self.url, params={"search": search_term})
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["count"], len(expected_pks))
        self.assertEqual({item["id"] for item in data["results"]}, set(expected_pks))

        for item in data["results"]:
            self.assert_api_format(item, AccountCategory.objects.get(id=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.read"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_list_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.read"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_list_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Retrieve Operation
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), self.category_shire)

    def test_retrieve_response_general(self):
        # The relation unset: `account` is null, and still in the response.
        response = self.do_request("GET", self.url_detail_general)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, self.category_general)
        self.assertIsNone(data["account"])

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{CATEGORY_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.read"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_retrieve_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.read"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.read"], 403),
        ]
    )
    def test_retrieve_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Create Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422, "name"),
            ({"name": "Pipe-weed"}, 422, None),  # taken on that account: unkeyed
            ({"name": "Second Breakfast"}, 201, None),  # a general name, reused on an account
            ({"name": "Second Breakfast", "account": None}, 422, None),  # taken among the general ones
            ({"color": -1}, 422, "color"),
            ({"color": 16}, 422, "color"),
            ({"color": None}, 422, "color"),
            ({"account": None}, 201, None),
            ({"account": "01JA0000000000000000000099"}, 422, "account"),
        ]
    )
    def test_create_request_field_validation(self, extra_body, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])

    def test_create_response(self):
        response = self.do_request("POST", self.url, data=self.payload_create)
        data = response.json()

        self.assertEqual(response.status_code, 201)
        self.assert_api_format(data, AccountCategory.objects.get(id=data["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.create"], 201),
            (["totem.accountcategory.read", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.create"], 403),
        ]
    )
    def test_create_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.create"], 201),
            (["totem.accountcategory.read", "totem.accountcategory.update", "totem.accountcategory.delete"], 403),
            (["totem.account.create"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update Operation
    # ------------------------------------------

    @parameterized.expand(
        [
            ({"name": None}, 422),
            ({"color": 16}, 422),
            ({"color": None}, 422),
            ({"name": "Second Breakfast"}, 200),  # only taken among the general ones
            ({"name": "Ale"}, 200),  # taken on another account only
        ]
    )
    def test_update_request_field_validation(self, extra_body, status_code):
        response = self.do_request("PATCH", self.url_detail, data={**self.payload_update, **extra_body})

        self.assertEqual(response.status_code, status_code)
        if status_code == 422:
            self.assertIn(next(iter(extra_body)), str(response.json()))

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(data, AccountCategory.objects.get(id=CATEGORY_SHIRE_ID))
        self.assertEqual((data["name"], data["color"]), ("Old Toby", 7))

    def test_update_ignores_the_account(self):
        # Not in the update schema: the scope of a category is fixed at creation.
        response = self.do_request("PATCH", self.url_detail, data={"account": ACCOUNT_ID2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccountCategory.objects.get(pk=CATEGORY_SHIRE_ID).account_id, ACCOUNT_ID1)

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{CATEGORY_ID4}/", data=self.payload_update)

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.update"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.read", "totem.accountcategory.delete"], 403),
            (["totem.account.update"], 403),
        ]
    )
    def test_update_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.update"], 200),
            (["totem.accountcategory.create", "totem.accountcategory.read", "totem.accountcategory.delete"], 403),
            (["totem.account.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data=self.payload_update)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Delete Operation
    # ------------------------------------------

    def test_delete_response(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertFalse(AccountCategory.objects.filter(pk=CATEGORY_SHIRE_ID).exists())
        # Its movements stay, uncategorized.
        self.assertIsNone(AccountMovement.objects.get(pk=MOVEMENT_ID3).category_id)

    def test_delete_not_found(self):
        response = self.do_request("DELETE", f"{self.url}{CATEGORY_ID4}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.delete"], 204),
            (["totem.accountcategory.create", "totem.accountcategory.read", "totem.accountcategory.update"], 403),
            (["totem.account.delete"], 403),
        ]
    )
    def test_delete_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.accountcategory.delete"], 204),
            (["totem.accountcategory.create", "totem.accountcategory.read", "totem.accountcategory.update"], 403),
            (["totem.account.delete"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        """ Call the API as Frodon (`auth="user"`) or as the API key (`"apikey"`).

        Frodon's token is minted on each call from the permissions his roles hold
        at that moment, as the login would.
        """
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or CATEGORY_FIELDS

        if "id" in fields:
            self.assertEqual(api_data["id"], str(obj.id))
        if "name" in fields:
            self.assertEqual(api_data["name"], obj.name)
        if "color" in fields:
            self.assertEqual(api_data["color"], obj.color)
        if "account" in fields:
            if obj.account is None:
                self.assertIsNone(api_data["account"])
            else:
                self.assertEqual(
                    api_data["account"],
                    {"id": obj.account.pk, "code": obj.account.code, "name": obj.account.name},
                )

        self.assertEqual(set(fields), set(api_data))
