from django.test import TestCase
from parameterized import parameterized

from account.tests.test_api.common import PERMISSION_DENIED, CommonTestMixin
from authentication.testing import mint_access_token
from core.testing import APITestCaseMixin
from payment.models import PaymentMethod
from user.access_rights import get_user_scopes

METHOD_CASH_ID = "01JW0000000000000000000001"
METHOD_BANK_ID = "01JW0000000000000000000002"

IBAN_BANK = "FR7630006000011234567890189"
IBAN_OTHER = "DE89370400440532013000"

METHOD_SCOPES = [
    "totem.paymentmethod.create",
    "totem.paymentmethod.read",
    "totem.paymentmethod.update",
    "totem.paymentmethod.delete",
]

PAYMENT_METHOD_FIELDS = ["id", "sequence", "active", "name", "code", "type", "iban"]


class PaymentMethodAPITest(CommonTestMixin, APITestCaseMixin, TestCase):
    """ `/payment/methods/`: the IBAN of a bank method, read and written. Its
    rules are tested with the service (`test_payment_method`), and its format
    with the schemas.

    No access rules tests: no `BaseRule` is registered for `PaymentMethod`.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        PaymentMethod.objects.bulk_create([
            PaymentMethod(id=METHOD_CASH_ID, sequence=1, code="CASH", name="Cash", type="cash"),
            PaymentMethod(id=METHOD_BANK_ID, sequence=2, code="BANK", name="Bank", type="bank", iban=IBAN_BANK),
        ])
        cls.role.permissions = METHOD_SCOPES
        cls.role.rules = []
        cls.role.save()
        cls.url = "/api/v1/payment/methods/"
        cls.url_bank = f"/api/v1/payment/methods/{METHOD_BANK_ID}/"

    # ------------------------------------------
    # List
    # ------------------------------------------

    def test_list_response(self):
        response = self.do_request("GET", self.url)

        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        self.assertEqual([item["id"] for item in results], [METHOD_CASH_ID, METHOD_BANK_ID])
        for item in results:
            self.assert_api_format(item, PaymentMethod.objects.get(pk=item["id"]))

    @parameterized.expand(
        [
            ("an iban", {"search": "FR7630006"}, [METHOD_BANK_ID]),
            ("the type", {"type": "bank"}, [METHOD_BANK_ID]),
        ]
    )
    def test_list_filters(self, label, params, expected_pks):
        response = self.do_request("GET", self.url, params=params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], expected_pks)

    # ------------------------------------------
    # Create
    # ------------------------------------------

    def test_create_response(self):
        payload = {"code": "SAVINGS", "name": "Savings", "type": "bank", "iban": "de89 3704 0044 0532 0130 00"}
        response = self.do_request("POST", self.url, data=payload)

        self.assertEqual(response.status_code, 201, response.json())
        method = PaymentMethod.objects.get(pk=response.json()["id"])
        # Read back in its electronic form, as stored.
        self.assertEqual(method.iban, IBAN_OTHER)
        self.assert_api_format(response.json(), method)

    @parameterized.expand(
        [
            # The schema: the validator of the field.
            ("wrong check digits", {"type": "bank", "iban": "FR7630006000011234567890188"}),
            ("not an iban", {"type": "bank", "iban": "FR76-3000!"}),
            # The service: the IBAN follows the type.
            ("a bank method without iban", {"type": "bank"}),
            ("a cash method with an iban", {"type": "cash", "iban": IBAN_OTHER}),
        ]
    )
    def test_create_request_field_validation(self, label, payload):
        response = self.do_request("POST", self.url, data={"code": "NEW", "name": "New", **payload})

        self.assertEqual(response.status_code, 422, response.json())
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], ["iban"])
        self.assertFalse(PaymentMethod.objects.filter(code="NEW").exists())

    @parameterized.expand(
        [
            ("no scope", [], 403),
            ("create", ["totem.paymentmethod.create"], 201),
            (
                "the other scopes",
                ["totem.paymentmethod.read", "totem.paymentmethod.update", "totem.paymentmethod.delete"],
                403,
            ),
        ]
    )
    def test_create_user_access_rights(self, label, permissions, status_code):
        self.role.permissions = permissions
        self.role.save()

        response = self.do_request(
            "POST", self.url, data={"code": "NEW", "name": "New", "type": "bank", "iban": IBAN_OTHER}
        )

        self.assertEqual(response.status_code, status_code)
        if status_code == 403:
            self.assertEqual(response.json(), PERMISSION_DENIED)

    # ------------------------------------------
    # Update
    # ------------------------------------------

    def test_update_response(self):
        response = self.do_request("PATCH", self.url_bank, data={"iban": "DE89 3704 0044 0532 0130 00"})

        self.assertEqual(response.status_code, 200, response.json())
        method = PaymentMethod.objects.get(pk=METHOD_BANK_ID)
        self.assertEqual(method.iban, IBAN_OTHER)
        self.assert_api_format(response.json(), method)

    @parameterized.expand(
        [
            ("wrong check digits", METHOD_BANK_ID, {"iban": "FR7630006000011234567890188"}),
            ("a bank method loses its iban", METHOD_BANK_ID, {"iban": None}),
            # The IBAN stays, the type changes under it.
            ("a bank method made a cash one", METHOD_BANK_ID, {"type": "cash"}),
            ("a cash method made a bank one", METHOD_CASH_ID, {"type": "bank"}),
        ]
    )
    def test_update_request_field_validation(self, label, pk, payload):
        before = PaymentMethod.objects.values("type", "iban").get(pk=pk)

        response = self.do_request("PATCH", f"{self.url}{pk}/", data=payload)

        self.assertEqual(response.status_code, 422, response.json())
        self.assertEqual([detail["loc"][-1] for detail in response.json()["detail"]], ["iban"])
        self.assertEqual(PaymentMethod.objects.values("type", "iban").get(pk=pk), before)

    # ------------------------------------------
    # Display name
    # ------------------------------------------

    def test_display_name_has_no_iban(self):
        # What a payment shows of its method: not the bank account.
        response = self.do_request("GET", f"{self.url}display-name/", params={"id": METHOD_BANK_ID})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), [{"id": METHOD_BANK_ID, "code": "BANK", "name": "Bank", "type": "bank"}]
        )

    # ------------------------------------------
    # Utils
    # ------------------------------------------

    def do_request(self, method, url, auth="user", data=None, params=None):
        if auth == "apikey":
            return self.do_api_key_request(url, method, self.api_key_secret, data=data, params=params or {})
        token = mint_access_token(self.user_frodon, get_user_scopes(self.user_frodon))
        return self.do_api_request(url, method, token, data=data, params=params or {})

    def assert_api_format(self, api_data, obj):
        for name in PAYMENT_METHOD_FIELDS:
            self.assertEqual(api_data[name], getattr(obj, name))
        self.assertEqual(set(PAYMENT_METHOD_FIELDS), set(api_data))
