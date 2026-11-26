from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountMovement, Invoice
from account.tests.test_api.common import PERMISSION_DENIED, CommonTestMixin
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from payment.models import Payment, PaymentMethod
from user.access_rights import get_user_scopes

INVOICE_ID1 = "01JV0000000000000000000001"
METHOD_BANK_ID = "01JW0000000000000000000002"
PAYMENT_ID1 = "01JX0000000000000000000001"
PAYMENT_ID2 = "01JX0000000000000000000002"
PAYMENT_UNKNOWN_ID = "01JX0000000000000000000099"
METHOD_UNKNOWN_ID = "01JW0000000000000000000099"
MOVEMENT_ID1 = "01JM0000000000000000000091"

METHOD_SCOPES = [
    "totem.paymentmethod.create",
    "totem.paymentmethod.read",
    "totem.paymentmethod.update",
    "totem.paymentmethod.delete",
]

PAYMENT_SCOPES = ["totem.payment.create", "totem.payment.read", "totem.payment.update", "totem.payment.delete"]

PAYMENT_FIELDS = [
    "id", "date", "amount", "currency_code", "direction", "state", "payment_method", "contact",
    "reference", "target_type", "invoice", "done_date", "account_movement", "create_date", "update_date",
]


@freeze_time("2026-10-20 10:00:00")
class PaymentAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `/payment/payments/`, under the scopes of `payment`. The routes of a
    document's payments are tested with it (`account.tests.test_api.test_invoice_payments`).

    The invoice is paid 10.00 by PAYMENT_ID1, done, with its movement booked;
    PAYMENT_ID2 is a draft settling nothing.

    No access rules tests: no `BaseRule` is registered for `Payment`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.invoice = Invoice.objects.create(
            id=INVOICE_ID1, name="Pipe-weed", date="2026-10-15", contact=cls.contact_tobold, account=cls.account_shire,
            amount_total=Decimal("100.00"),
        )
        cls.method_bank = PaymentMethod.objects.create(
            id=METHOD_BANK_ID, code="BANK", name="Bank", type="bank", iban="FR7630006000011234567890189"
        )
        # Done, with the movement it booked: written as `PaymentService` would.
        movement = AccountMovement.objects.create(
            id=MOVEMENT_ID1, name="Payment", amount=Decimal("-10.00"), date="2026-10-16",
            account=cls.account_shire, origin_type="invoice", invoice=cls.invoice,
        )
        Payment.objects.bulk_create([
            Payment(
                id=PAYMENT_ID1, date="2026-10-16", amount=Decimal("10.00"), direction="outgoing",
                state="done", payment_method=cls.method_bank, target_type="invoice", invoice=cls.invoice,
                account_movement=movement,
            ),
            Payment(
                id=PAYMENT_ID2, date="2026-10-17", amount=Decimal("5.00"), direction="incoming",
                payment_method=cls.method_bank, contact=cls.contact_lobelia,
            ),
        ])
        # Bulk-created: the invoice is told of its payment, 90.00 left to pay.
        Invoice.objects.refresh_computed()
        cls.role.permissions = PAYMENT_SCOPES
        cls.role.rules = []
        cls.role.save()
        cls.url = "/api/v1/payment/payments/"
        cls.url_detail = f"/api/v1/payment/payments/{PAYMENT_ID1}/"
        cls.url_detail_draft = f"/api/v1/payment/payments/{PAYMENT_ID2}/"

    payload_create = {
        "date": "2026-10-18",
        "amount": "30.00",
        "direction": "outgoing",
        "payment_method": METHOD_BANK_ID,
        "reference": "TRF-2",
    }

    # ------------------------------------------
    # List
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual([item["id"] for item in results], [PAYMENT_ID2, PAYMENT_ID1])
        for item in results:
            self.assert_api_format(item, Payment.objects.get(pk=item["id"]))

    def test_list_fields_response(self):
        """The one-to-one to the movement, prefetched, caches the payment on the
        movement too: the list used to follow it back until a RecursionError."""
        fields = "id,date,reference,contact,payment_method,direction,amount,currency_code,state,invoice,account_movement"
        response = self.do_request("GET", self.url, params={"fields": fields, "ordering": "date"})

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual([item["id"] for item in results], [PAYMENT_ID1, PAYMENT_ID2])
        for item in results:
            self.assert_api_format(item, Payment.objects.get(pk=item["id"]), fields.split(","))

    @parameterized.expand(
        [
            ("of an invoice", {"target_type": "invoice"}, [PAYMENT_ID1]),
            ("of no document", {"target_type": "null"}, [PAYMENT_ID2]),
            ("the invoice", {"invoice": INVOICE_ID1}, [PAYMENT_ID1]),
            ("incoming", {"direction": "incoming"}, [PAYMENT_ID2]),
        ]
    )
    def test_list_filters(self, label, params, expected_pks):
        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], expected_pks)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("read", ["totem.payment.read"], 200),
            ("the other scopes", ["totem.payment.create", "totem.payment.update", "totem.payment.delete"], 403),
            ("another resource", METHOD_SCOPES, 403),
        ]
    )
    def test_list_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("read", ["totem.payment.read"], 200),
            ("the other scopes", ["totem.payment.create", "totem.payment.update", "totem.payment.delete"], 403),
            ("another resource", METHOD_SCOPES, 403),
        ]
    )
    def test_list_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Retrieve
    # ------------------------------------------

    def test_retrieve_response(self):
        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, 200)
        self.assert_api_format(response.json(), Payment.objects.get(pk=PAYMENT_ID1))

    def test_retrieve_not_found(self):
        response = self.do_request("GET", f"{self.url}{PAYMENT_UNKNOWN_ID}/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("read", ["totem.payment.read"], 200),
            ("the other scopes", ["totem.payment.create", "totem.payment.update", "totem.payment.delete"], 403),
            ("another resource", METHOD_SCOPES, 403),
        ]
    )
    def test_retrieve_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url_detail)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    @parameterized.expand(
        [
            ("settling nothing", {}, 201, None),
            ("settling the invoice", {"target_type": "invoice", "invoice": INVOICE_ID1}, 201, None),
            ("no amount", {"amount": None}, 422, "amount"),
            ("a zero amount", {"amount": "0"}, 422, "amount"),
            ("an unknown state", {"state": "lost"}, 422, "state"),
            ("an unknown method", {"payment_method": METHOD_UNKNOWN_ID}, 422, "payment_method"),
            ("an invoice without target type", {"invoice": INVOICE_ID1}, 422, "invoice"),
            # The rules of the invoice apply here too: 90.00 is left to pay.
            (
                "beyond what the invoice is due",
                {"state": "done", "amount": "90.01", "target_type": "invoice", "invoice": INVOICE_ID1},
                422, "amount",
            ),
        ]
    )
    def test_create_request_field_validation(self, label, extra, status_code, error_field):
        response = self.do_request("POST", self.url, data={**self.payload_create, **extra})

        self.assertEqual(response.status_code, status_code, response.json())
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])
            self.assertEqual(Payment.objects.count(), 2)

    def test_create_response(self):
        response = self.do_request(
            "POST", self.url,
            data={**self.payload_create, "state": "done", "target_type": "invoice", "invoice": INVOICE_ID1},
        )

        self.assertEqual(response.status_code, 201, response.json())
        payment = Payment.objects.get(pk=response.json()["id"])
        # Done on an invoice: its movement is booked, and read back.
        self.assertIsNotNone(payment.account_movement_id)
        self.assert_api_format(response.json(), payment)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("create", ["totem.payment.create"], 201),
            ("the other scopes", ["totem.payment.read", "totem.payment.update", "totem.payment.delete"], 403),
            # The scope of the document does not open the generic route.
            ("the invoice's", ["totem.invoice.update"], 403),
        ]
    )
    def test_create_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("create", ["totem.payment.create"], 201),
            ("the other scopes", ["totem.payment.read", "totem.payment.update", "totem.payment.delete"], 403),
            ("the invoice's", ["totem.invoice.update"], 403),
        ]
    )
    def test_create_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload_create)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Default Values
    # ------------------------------------------

    @parameterized.expand([("user",), ("apikey",)])
    def test_default_value_response(self, auth):
        response = self.do_request("GET", f"{self.url}default-values/", auth=auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {name: value for name, value in response.json().items() if value is not None},
            {"state": "draft", "currency_code": "EUR"},
        )

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("a reference", {"reference": "TRF-1b"}, 200, None),
            ("cancelled", {"state": "cancelled"}, 200, None),
            ("a zero amount", {"amount": "0"}, 422, "amount"),
            ("an unknown method", {"payment_method": METHOD_UNKNOWN_ID}, 422, "payment_method"),
            # Its own 10.00 is due again once rewritten: 100.00 at most.
            ("beyond what the invoice is due", {"amount": "100.01"}, 422, "amount"),
            # A booked movement is the payment's: its amount follows, not refused.
            ("a new amount", {"amount": "25.00"}, 200, None),
        ]
    )
    def test_update_request_field_validation(self, label, payload, status_code, error_field):
        response = self.do_request("PATCH", self.url_detail, data=payload)

        self.assertEqual(response.status_code, status_code, response.json())
        if error_field:
            self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [error_field])
            self.assertEqual(Payment.objects.get(pk=PAYMENT_ID1).amount, Decimal("10.00"))

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data={"amount": "25.00", "reference": "TRF-1b"})

        self.assertEqual(response.status_code, 200, response.json())
        payment = Payment.objects.get(pk=PAYMENT_ID1)
        self.assertEqual((payment.amount, payment.reference), (Decimal("25.00"), "TRF-1b"))
        # The movement follows the payment.
        self.assertEqual(payment.account_movement.amount, Decimal("-25.00"))
        self.assert_api_format(response.json(), payment)

    def test_update_not_found(self):
        response = self.do_request("PATCH", f"{self.url}{PAYMENT_UNKNOWN_ID}/", data={"reference": "TRF-9"})

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.payment.update"], 200),
            ("the other scopes", ["totem.payment.create", "totem.payment.read", "totem.payment.delete"], 403),
            ("the invoice's", ["totem.invoice.update"], 403),
        ]
    )
    def test_update_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data={"reference": "TRF-1b"})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.payment.update"], 200),
            ("the other scopes", ["totem.payment.create", "totem.payment.read", "totem.payment.delete"], 403),
            ("the invoice's", ["totem.invoice.update"], 403),
        ]
    )
    def test_update_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data={"reference": "TRF-1b"})

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Delete
    # ------------------------------------------

    def test_delete_response(self):
        # The draft: a done payment must be cancelled first.
        response = self.do_request("DELETE", self.url_detail_draft)

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Payment.objects.filter(pk=PAYMENT_ID2).exists())

    def test_delete_refused(self):
        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 422, response.json())
        self.assertTrue(Payment.objects.filter(pk=PAYMENT_ID1).exists())

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("delete", ["totem.payment.delete"], 204),
            ("the other scopes", ["totem.payment.create", "totem.payment.read", "totem.payment.update"], 403),
            ("the invoice's", ["totem.invoice.update"], 403),
        ]
    )
    def test_delete_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail_draft)

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Payment.objects.filter(pk=PAYMENT_ID2).exists(), status_code != 204)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("delete", ["totem.payment.delete"], 204),
            ("the other scopes", ["totem.payment.create", "totem.payment.read", "totem.payment.update"], 403),
            ("the invoice's", ["totem.invoice.update"], 403),
        ]
    )
    def test_delete_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail_draft, auth="apikey")

        self.assertEqual(response.status_code, status_code)
        self.assertEqual(Payment.objects.filter(pk=PAYMENT_ID2).exists(), status_code != 204)
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

    def assert_api_format(self, api_data, obj, fields=None):
        fields = fields or PAYMENT_FIELDS

        for name in ("id", "currency_code", "direction", "state", "reference", "target_type"):
            if name in fields:
                self.assertEqual(api_data[name], getattr(obj, name))
        self.assertEqual(Decimal(api_data["amount"]), obj.amount)
        self.assertEqual(api_data["payment_method"]["id"], obj.payment_method_id)
        invoice = obj.invoice
        self.assertEqual(
            api_data["invoice"],
            {"id": invoice.pk, "number": invoice.number, "name": invoice.name, "reference": invoice.reference}
            if invoice else None,
        )
        self.assertEqual(api_data["contact"]["id"] if api_data["contact"] else None, obj.contact_id)
        movement = obj.account_movement
        self.assertEqual(
            api_data["account_movement"],
            {"id": movement.pk, "name": movement.name, "amount": str(movement.amount), "date": movement.date.isoformat()}
            if movement else None,
        )
        self.assertEqual(set(fields), set(api_data))
