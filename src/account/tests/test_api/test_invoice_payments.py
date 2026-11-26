from decimal import Decimal

from django.test import TestCase
from freezegun import freeze_time
from parameterized import parameterized

from account.models import AccountMovement, Invoice
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from payment.models import Payment, PaymentMethod
from user.access_rights import get_user_scopes

from .common import ACCOUNT_ID1, INVOICE_SCOPES, PERMISSION_DENIED, CommonTestMixin

INVOICE_ID1 = "01JV0000000000000000000001"
INVOICE_ID2 = "01JV0000000000000000000002"
METHOD_BANK_ID = "01JW0000000000000000000002"
PAYMENT_ID1 = "01JX0000000000000000000001"
PAYMENT_UNKNOWN_ID = "01JX0000000000000000000099"

# Neither `state` nor `contact`: every payment of an invoice is done, and paid
# to its supplier.
PAYMENT_FIELDS = [
    "id", "date", "amount", "currency_code", "direction", "payment_method", "reference",
    "done_date", "account_movement", "create_date", "update_date",
]

# Every scope of an invoice but `update`, which the payment routes require.
OTHER_INVOICE_SCOPES = ["totem.invoice.create", "totem.invoice.read", "totem.invoice.delete"]


@freeze_time("2026-10-20 10:00:00")
class InvoicePaymentsAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `/accounting/invoices/{id}/payments/`: the payments of an invoice, listed
    under it with the `totem.invoice.read` scope, and registered, changed and
    deleted there with `totem.invoice.update` (`PaymentTargetModelControllerMixin`). The rules of a payment of an invoice
    are tested on the service (`test_invoice_payment`); here, what the routes add:
    the invoice of the path, the body, the response, the scopes.

    No access rules tests: no `BaseRule` is registered for `Invoice` nor
    `Payment`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.invoice, cls.invoice_other = Invoice.objects.bulk_create([
            Invoice(
                id=INVOICE_ID1, date="2026-10-15", contact=cls.contact_tobold, account=cls.account_shire,
                amount_total=Decimal("100.00"),
            ),
            Invoice(
                id=INVOICE_ID2, date="2026-10-15", contact=cls.contact_lobelia, account=cls.account_shire,
                amount_total=Decimal("40.00"),
            ),
        ])
        Invoice.objects.refresh_computed()
        cls.method_bank = PaymentMethod.objects.create(
            id=METHOD_BANK_ID, code="BANK", name="Bank", type="bank", iban="FR7630006000011234567890189"
        )
        # Written past the service: done, but no movement booked; the routes book
        # it on the first write.
        cls.payment = Payment.objects.create(
            id=PAYMENT_ID1, date="2026-10-16", amount=Decimal("10.00"), direction="outgoing", state="done",
            payment_method=cls.method_bank, target_type="invoice", invoice=cls.invoice,
        )
        Invoice.objects.refresh_computed()
        cls.role.permissions = ["totem.invoice.update"]
        cls.role.rules = []
        cls.role.save()
        cls.url = f"/api/v1/accounting/invoices/{INVOICE_ID1}/payments/"
        cls.url_detail = f"/api/v1/accounting/invoices/{INVOICE_ID1}/payments/{PAYMENT_ID1}/"

    payload = {"date": "2026-10-18", "amount": "60.00", "payment_method": METHOD_BANK_ID}

    # ------------------------------------------
    # List
    # ------------------------------------------

    def test_payment_list_response(self):
        # One of another invoice, and one of this invoice not done: not listed.
        Payment.objects.bulk_create([
            Payment(
                date="2026-10-16", amount=Decimal("3.00"), direction="outgoing", state="done",
                payment_method=self.method_bank, target_type="invoice", invoice=self.invoice_other,
            ),
            Payment(
                date="2026-10-17", amount=Decimal("4.00"), direction="outgoing", state="pending",
                payment_method=self.method_bank, target_type="invoice", invoice=self.invoice,
            ),
        ])
        self.role.permissions = ["totem.invoice.read"]
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200, response.json())
        # Not paginated: a list, not a page.
        self.assertEqual([item["id"] for item in response.json()], [PAYMENT_ID1])
        self.assert_api_format(response.json()[0], Payment.objects.get(pk=PAYMENT_ID1))

    def test_payment_list_unknown_invoice(self):
        self.role.permissions = ["totem.invoice.read"]
        self.role.save()

        response = self.do_request("GET", "/api/v1/accounting/invoices/01JV0000000000000000000099/payments/")

        self.assertEqual(response.status_code, 404)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("read", ["totem.invoice.read"], 200),
            # The scope of the writes does not open the list.
            ("the other scopes", ["totem.invoice.create", "totem.invoice.update", "totem.invoice.delete"], 403),
            ("payment read", ["totem.payment.read"], 403),
        ]
    )
    def test_payment_list_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("read", ["totem.invoice.read"], 200),
            ("the other scopes", ["totem.invoice.create", "totem.invoice.update", "totem.invoice.delete"], 403),
        ]
    )
    def test_payment_list_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("GET", self.url, auth="apikey")

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Register
    # ------------------------------------------

    @parameterized.expand(
        [
            ("an unknown direction", {"direction": "sideways"}, "direction"),
            ("an incoming payment", {"direction": "incoming"}, "direction"),
            # 10.00 already paid by PAYMENT_ID1.
            ("more than due", {"amount": "90.01"}, "amount"),
            ("no amount", {"amount": None}, "amount"),
            ("an unknown method", {"payment_method": "01JW0000000000000000000099"}, "payment_method"),
        ]
    )
    def test_payment_register_request(self, label, extra, field):
        response = self.do_request("POST", self.url, data={**self.payload, **extra})

        self.assertEqual(response.status_code, 422, response.json())
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [field])
        self.assertEqual(Payment.objects.count(), 1)

    def test_payment_register_ignores_what_it_forces(self):
        # The target, the state and the contact are no part of the body: the
        # invoice is the path's, the payment done, paid to the invoice's supplier.
        response = self.do_request(
            "POST", self.url, data={
                **self.payload, "target_type": None, "invoice": INVOICE_ID2, "state": "draft",
                "contact": self.contact_lobelia.pk,
            }
        )

        self.assertEqual(response.status_code, 201, response.json())
        payment = Payment.objects.get(pk=response.json()["id"])
        self.assertEqual(
            (payment.invoice_id, payment.state, payment.contact_id), (INVOICE_ID1, "done", self.contact_tobold.pk)
        )

    def test_payment_register_response(self):
        response = self.do_request("POST", self.url, data=self.payload)

        self.assertEqual(response.status_code, 201, response.json())
        payment = Payment.objects.get(pk=response.json()["id"])
        self.assertEqual(
            (payment.target_type, payment.invoice_id, payment.direction, payment.contact_id),
            ("invoice", INVOICE_ID1, "outgoing", self.contact_tobold.pk),
        )
        movement = AccountMovement.objects.get(pk=payment.account_movement_id)
        self.assertEqual((movement.account_id, movement.amount), (ACCOUNT_ID1, Decimal("-60.00")))
        self.assertEqual(Invoice.objects.get(pk=INVOICE_ID1).payment_status, "partially_paid")
        self.assert_api_format(response.json(), payment)

    def test_payment_register_unknown_invoice(self):
        response = self.do_request(
            "POST", "/api/v1/accounting/invoices/01JV0000000000000000000099/payments/", data=self.payload
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Payment.objects.count(), 1)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.invoice.update"], 201),
            ("the other scopes", OTHER_INVOICE_SCOPES, 403),
            # Paying an invoice is not writing a payment: no scope of `payment` opens it.
            ("payment read", ["totem.payment.read"], 403),
        ]
    )
    def test_payment_register_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("POST", self.url, data=self.payload)

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.invoice.update"], 201),
            ("the other scopes", OTHER_INVOICE_SCOPES, 403),
        ]
    )
    def test_payment_register_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("POST", self.url, auth="apikey", data=self.payload)

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    @parameterized.expand(
        [
            ("an unknown direction", {"direction": "sideways"}, "direction"),
            ("a zero amount", {"amount": "0"}, "amount"),
            ("another currency", {"currency_code": "USD"}, "currency_code"),
        ]
    )
    def test_payment_update_request(self, label, data, field):
        response = self.do_request("PATCH", self.url_detail, data=data)

        self.assertEqual(response.status_code, 422, response.json())
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], [field])
        self.assertEqual(Payment.objects.get(pk=PAYMENT_ID1).amount, Decimal("10.00"))

    def test_payment_update_response(self):
        response = self.do_request("PATCH", self.url_detail, data={"amount": "25.00"})

        self.assertEqual(response.status_code, 200, response.json())
        payment = Payment.objects.get(pk=PAYMENT_ID1)
        self.assertEqual(payment.amount, Decimal("25.00"))
        self.assertEqual(payment.account_movement.amount, Decimal("-25.00"))
        self.assert_api_format(response.json(), payment)

    @parameterized.expand(
        [
            ("of another invoice", f"/api/v1/accounting/invoices/{INVOICE_ID2}/payments/{PAYMENT_ID1}/"),
            ("unknown", f"/api/v1/accounting/invoices/{INVOICE_ID1}/payments/{PAYMENT_UNKNOWN_ID}/"),
        ]
    )
    def test_payment_update_not_found(self, label, url):
        response = self.do_request("PATCH", url, data={"amount": "25.00"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Payment.objects.get(pk=PAYMENT_ID1).amount, Decimal("10.00"))

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.invoice.update"], 200),
            ("the other scopes", OTHER_INVOICE_SCOPES, 403),
        ]
    )
    def test_payment_update_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("PATCH", self.url_detail, data={"reference": "TRF-9"})

        self.assertEqual(response.status_code, status_code)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.invoice.update"], 200),
            ("the other scopes", OTHER_INVOICE_SCOPES, 403),
        ]
    )
    def test_payment_update_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("PATCH", self.url_detail, auth="apikey", data={"reference": "TRF-9"})

        self.assertEqual(response.status_code, status_code)

    # ------------------------------------------
    # Cancel (DELETE)
    # ------------------------------------------

    def test_payment_cancel_response(self):
        # Booked first, so that cancelling it takes something back.
        self.do_request("PATCH", self.url_detail, data={"reference": "TRF-1"})
        movement_id = Payment.objects.get(pk=PAYMENT_ID1).account_movement_id

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, 204)
        # Cancelled, not deleted: the payment stays, as a trace.
        self.assertEqual(Payment.objects.get(pk=PAYMENT_ID1).state, "cancelled")
        self.assertFalse(AccountMovement.objects.filter(pk=movement_id).exists())
        self.assertEqual(Invoice.objects.get(pk=INVOICE_ID1).payment_status, "not_paid")
        # Out of reach of the routes now: a second DELETE finds nothing.
        self.assertEqual(self.do_request("DELETE", self.url_detail).status_code, 404)

    @parameterized.expand(
        [
            ("of another invoice", f"/api/v1/accounting/invoices/{INVOICE_ID2}/payments/{PAYMENT_ID1}/"),
            ("unknown", f"/api/v1/accounting/invoices/{INVOICE_ID1}/payments/{PAYMENT_UNKNOWN_ID}/"),
        ]
    )
    def test_payment_cancel_not_found(self, label, url):
        response = self.do_request("DELETE", url)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Payment.objects.get(pk=PAYMENT_ID1).state, "done")

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.invoice.update"], 204),
            ("the other scopes", OTHER_INVOICE_SCOPES, 403),
        ]
    )
    def test_payment_cancel_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request("DELETE", self.url_detail)

        self.assertEqual(response.status_code, status_code)

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("update", ["totem.invoice.update"], 204),
            ("the other scopes", OTHER_INVOICE_SCOPES, 403),
        ]
    )
    def test_payment_cancel_apikey_access_rights(self, label, permissions, status_code):
        self.api_key.scope = permissions
        self.api_key.save()

        response = self.do_request("DELETE", self.url_detail, auth="apikey")

        self.assertEqual(response.status_code, status_code)

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

        for name in ("id", "currency_code", "direction", "reference"):
            self.assertEqual(api_data[name], getattr(obj, name))
        self.assertEqual(Decimal(api_data["amount"]), obj.amount)
        self.assertEqual(api_data["payment_method"]["id"], obj.payment_method_id)
        # No `target_type` nor `invoice`: the invoice is the one of the path, which
        # the last line pins.
        if obj.account_movement_id is None:
            self.assertIsNone(api_data["account_movement"])
        else:
            self.assertEqual(api_data["account_movement"]["id"], obj.account_movement_id)
            self.assertEqual(Decimal(api_data["account_movement"]["amount"]), obj.account_movement.amount)
        self.assertEqual(set(fields), set(api_data))
