"""The payments of an invoice, as its routes read and write them
(`InvoiceController`, through `PaymentTargetModelControllerMixin`).

The schemas of `payment`, under names of their own. No target in the response:
the invoice is the one of the path."""

from payment.schemas import PaymentChangeSchema, PaymentOfDocumentSchema, PaymentRegisterSchema


class InvoicePaymentSchema(PaymentOfDocumentSchema):
    pass


class InvoicePaymentCreateSchema(PaymentRegisterSchema):
    pass


class InvoicePaymentUpdateSchema(PaymentChangeSchema):
    pass
