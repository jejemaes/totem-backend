from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.client import MULTIPART_CONTENT
from freezegun import freeze_time
from parameterized import parameterized

from account.models import Invoice
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin, MediaRootTestMixin
from document.tests.images import pdf_bytes
from user.access_rights import get_user_scopes

from .common import (
    ACCOUNT_ID1,
    ACCOUNT_ID2,
    CATEGORY_BREE_ID,
    CATEGORY_SHIRE_ID,
    CONTACT_TOBOLD_ID,
    INVOICE_SCOPES,
    MOVEMENT_SCOPES,
    PERMISSION_DENIED,
    CommonTestMixin,
)

INVOICE_ID1 = "01JV0000000000000000000001"
INVOICE_ID2 = "01JV0000000000000000000002"

INVOICE_FIELDS = [
    "id", "number", "name", "reference", "date", "due_date", "contact", "account", "category", "description",
    "amount_total", "currency_code", "file_content", "file_mimetype", "create_date", "update_date",
]


@freeze_time("2026-10-20 10:00:00")
class InvoiceAPITest(CommonTestMixin, MediaRootTestMixin, APITestCaseMixin, TestCase):
    """ `/accounting/invoices/`: the multipart creation, the list and its filters,
    the scopes.

    No access rules tests: no `BaseRule` is registered for `Invoice`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.invoice_pipeweed, cls.invoice_ale = Invoice.objects.bulk_create([
            Invoice(
                id=INVOICE_ID1, name="Pipe-weed", reference="OLD-TOBY-7", date="2026-10-15", contact=cls.contact_tobold,
                account=cls.account_shire, category=cls.category_shire, amount_total=Decimal("100.00"),
            ),
            Invoice(
                id=INVOICE_ID2, date="2026-09-01", contact=cls.contact_lobelia,
                account=cls.account_bree, amount_total=Decimal("40.00"), currency_code="USD",
            ),
        ])
        cls.role.permissions = INVOICE_SCOPES
        cls.role.rules = []
        cls.role.save()
        cls.url = "/api/v1/accounting/invoices/"
        cls.url_detail = f"/api/v1/accounting/invoices/{INVOICE_ID1}/"

    payload_create = {
        "date": "2026-10-18",
        "contact": CONTACT_TOBOLD_ID,
        "account": ACCOUNT_ID1,
        "amount_total": "25.00",
        "reference": "OLD-TOBY-8",
        "name": "More pipe-weed",
        "category": CATEGORY_SHIRE_ID,
    }

    # ------------------------------------------
    # List
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        # Newest first.
        self.assertEqual([item["id"] for item in results], [INVOICE_ID1, INVOICE_ID2])
        # Read back: the bulk-created instance still holds its date as a string.
        self.assert_api_format(results[0], Invoice.objects.get(pk=INVOICE_ID1))

    @parameterized.expand(
        [
            ("contact", {"contact": CONTACT_TOBOLD_ID}, [INVOICE_ID1]),
            ("account", {"account": ACCOUNT_ID1}, [INVOICE_ID1]),
            ("category", {"category": CATEGORY_SHIRE_ID}, [INVOICE_ID1]),
            ("no category", {"category": "null"}, [INVOICE_ID2]),
            ("from", {"date_from": "2026-10-01"}, [INVOICE_ID1]),
            ("search the number", {"search": "00002"}, [INVOICE_ID2]),
            ("search the reference", {"search": "toby"}, [INVOICE_ID1]),
            ("search the name", {"search": "weed"}, [INVOICE_ID1]),
        ]
    )
    def test_list_filters(self, label, params, expected_pks):
        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], expected_pks)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("read", ["totem.invoice.read"], 200),
            ("the other scopes", ["totem.invoice.create", "totem.invoice.update", "totem.invoice.delete"], 403),
            ("another resource", MOVEMENT_SCOPES, 403),
        ]
    )
    def test_list_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    def test_create_response(self):
        upload = SimpleUploadedFile("bill.pdf", pdf_bytes(), content_type="application/pdf")
        response = self.do_request(
            "POST", self.url, data={**self.payload_create, "file_content": upload}, content_type=MULTIPART_CONTENT
        )

        self.assertEqual(response.status_code, 201, response.json())
        invoice = Invoice.objects.get(pk=response.json()["id"])
        self.assertEqual(invoice.number, "INV/2026/00003")
        self.assertEqual(invoice.file_mimetype, "application/pdf")
        self.assertTrue(invoice.file_content.name.startswith("account/invoice/2026/10/"))
        self.assert_api_format(response.json(), invoice)

    @parameterized.expand(
        [
            ("a text file", {"file_content": SimpleUploadedFile("bill.txt", b"owed")}, ["file", "file_content"]),
            ("a negative total", {"amount_total": "-3"}, ["form", "amount_total"]),
            ("no contact", {"contact": ""}, ["form", "contact"]),
            # The invoice is on SHIRE.
            ("a category of another account", {"category": CATEGORY_BREE_ID}, ["form", "category"]),
        ]
    )
    def test_create_request_field_validation(self, label, extra, loc):
        data = {**self.payload_create, **extra}
        if extra.get("contact") == "":
            del data["contact"]
        response = self.do_request("POST", self.url, data=data, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, 422, response.json())
        self.assertEqual([detail["loc"][0] for detail in response.json()["detail"]], [loc[0]])
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [loc[-1]])
        self.assertEqual(Invoice.objects.count(), 2)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("create", ["totem.invoice.create"], 201),
            ("the other scopes", ["totem.invoice.read", "totem.invoice.update", "totem.invoice.delete"], 403),
        ]
    )
    def test_create_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create, content_type=MULTIPART_CONTENT)

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data={"amount_total": "80.00"})

        self.assertEqual(response.status_code, 200, response.json())
        invoice = Invoice.objects.get(pk=INVOICE_ID1)
        self.assertEqual(invoice.amount_total, Decimal("80.00"))
        self.assert_api_format(response.json(), invoice)

    @parameterized.expand(
        [
            ("a category of another account", {"category": CATEGORY_BREE_ID}),
            # The category stays, the account changes under it.
            ("another account under its category", {"account": ACCOUNT_ID2}),
        ]
    )
    def test_update_request_field_validation(self, label, payload):
        response = self.do_request("PATCH", self.url_detail, data=payload)

        self.assertEqual(response.status_code, 422, response.json())
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], ["category"])
        invoice = Invoice.objects.get(pk=INVOICE_ID1)
        self.assertEqual((invoice.account_id, invoice.category_id), (ACCOUNT_ID1, CATEGORY_SHIRE_ID))

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None, content_type=None):
        extra = {"content_type": content_type} if content_type else {}
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {}, **extra)
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {}, **extra)

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or INVOICE_FIELDS

        for name in ("id", "number", "name", "reference", "description", "currency_code", "file_mimetype"):
            self.assertEqual(api_data[name], getattr(obj, name))
        self.assertEqual(Decimal(api_data["amount_total"]), obj.amount_total)
        self.assertEqual(api_data["date"], obj.date.isoformat())
        self.assertEqual(api_data["contact"]["id"], obj.contact_id)
        self.assertEqual(api_data["account"]["id"], obj.account_id)
        self.assertEqual(api_data["category"]["id"] if api_data["category"] else None, obj.category_id)
        if obj.file_content:
            self.assertEqual(
                api_data["file_content"].split("?")[0],
                obj.file_content.storage.url(obj.file_content.name).split("?")[0],
            )
        else:
            self.assertIsNone(api_data["file_content"])
        self.assertEqual(set(fields), set(api_data))
