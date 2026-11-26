from decimal import Decimal

from django.test import TestCase
from parameterized import parameterized

from account.models import Invoice
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from user.access_rights import get_user_scopes

from .common import INVOICE_SCOPES, MOVEMENT_SCOPES, PERMISSION_DENIED, CommonTestMixin

INVOICE_ID1 = "01JV0000000000000000000001"
INVOICE_ID2 = "01JV0000000000000000000002"


class InvoiceDisplayNameAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ The pipe-weed of Tobold, named by the user (INVOICE_ID1), and an invoice
    of Lobelia's without a name (INVOICE_ID2).

    No access rules tests: no `BaseRule` is registered for `Invoice`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Invoice.objects.bulk_create([
            Invoice(
                id=INVOICE_ID1, name="Pipe-weed", reference="OLD-TOBY-7", date="2026-10-15",
                contact=cls.contact_tobold, account=cls.account_shire, amount_total=Decimal("100.00"),
            ),
            Invoice(
                id=INVOICE_ID2, date="2026-09-01", contact=cls.contact_lobelia,
                account=cls.account_bree, amount_total=Decimal("40.00"),
            ),
        ])
        cls.role.permissions = INVOICE_SCOPES
        cls.role.rules = []
        cls.role.save()

        cls.url = "/api/v1/accounting/invoices/display-name/"
        cls.ids = f"{INVOICE_ID2},{INVOICE_ID1}"

    # ------------------------------------------
    # Display Name
    # ------------------------------------------

    @parameterized.expand(
        [
            # The order asked is the order returned.
            ({"id": f"{INVOICE_ID2},{INVOICE_ID1}"}, 200, [INVOICE_ID2, INVOICE_ID1]),
            ({"id": f"{INVOICE_ID1},{INVOICE_ID2}"}, 200, [INVOICE_ID1, INVOICE_ID2]),
            # An unknown id is absent, not an error.
            ({"id": f"{INVOICE_ID1},01JV0000000000000000000099"}, 200, [INVOICE_ID1]),
            ({"id": ""}, 200, []),
            # A missing or malformed id is the client's mistake.
            ({}, 422, None),
            ({"id": f"{INVOICE_ID1},old-toby"}, 422, None),
        ]
    )
    def test_display_name_request(self, params, status_code, expected_pks):
        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, status_code)
        if status_code == 200:
            self.assertEqual([item["id"] for item in response.json()], expected_pks)
        else:
            self.assertEqual(response.json()["detail"][0]["loc"][:2], ["query", "id"])

    def test_display_name_response(self):
        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        for item in response.json():
            self.assert_api_format(item, Invoice.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ([], 403),
            (["totem.invoice.read"], 200),
            (["totem.invoice.create", "totem.invoice.update", "totem.invoice.delete"], 403),
            (MOVEMENT_SCOPES, 403),
        ]
    )
    def test_display_name_user_access_rights(self, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url, params={"id": self.ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ([], 403),
            (["totem.invoice.read"], 200),
            (["totem.invoice.create", "totem.invoice.update", "totem.invoice.delete"], 403),
            (MOVEMENT_SCOPES, 403),
        ]
    )
    def test_display_name_apikey_access_rights(self, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey", params={"id": self.ids})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, obj):
        self.assertEqual(
            api_data, {"id": obj.pk, "number": obj.number, "name": obj.name, "reference": obj.reference}
        )
