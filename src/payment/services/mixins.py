"""What a document settled by payments composes in its service.

A payment settles at most one document: `Payment.target_type` names its kind,
and one foreign key per kind points at it. The behaviour proper to a kind -- its
defaults, its rules, the movement it books -- is the document's business, not
this app's: its service composes `PaymentTargetServiceMixin`, declares which
`target_type` and which foreign key are its own, and implements the hooks.
`PaymentService` finds them through `payment_target_registry`.

So `payment` imports nothing of the apps whose documents it settles, which
depend on it: the reverse would be an import cycle.
"""

import typing as t

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from pydantic import BaseModel

from payment.choices import PaymentState
from payment.models import Payment
from payment.schemas import PaymentCreateSchema, PaymentUpdateSchema

# `target_type` -> the service class of the documents of that kind. Filled when a
# service composing the mixin is declared; `payment.checks` makes sure every
# target type has one.
payment_target_registry: t.Dict[str, t.Type["PaymentTargetServiceMixin"]] = {}


class PaymentTargetServiceMixin:
    """The payments of a document, managed from its service.

    Declare:
    - `payment_target_type`: the `PaymentTargetType` value of the documents;
    - `payment_target_field`: the foreign key of `Payment` pointing at them.

    Implement, on an instance of the document (sync, inside the payment's write):
    - `_payment_default_values(target)`: the values a new payment takes when the
      input leaves them out, keyed by field name, relations as pks;
    - `_payment_validate(target, values, instance)`: the rules a payment of the
      document obeys; `values` are those the payment will hold once written,
      `instance` the payment before (None on creation). Raise a
      `ServiceValidationError` keyed by field;
    - `_payment_movement_values(target, payment)`: the `AccountMovement` a done
      payment books, as field values -- its account, sign, origin type and origin
      foreign key -- or None for none.

    Provides `payment_read`, `payment_register`, `payment_update` and
    `payment_cancel`: the payments of one document, `done` ones only. A payment
    is registered `done`, paid to the document's contact; cancelling one takes
    its movement back while the payment stays, as a trace -- `PaymentService`
    deletes no done payment. A payment of the document in any
    other state, written elsewhere, is out of reach here. Reading needs the
    document within the acting user's `read` rules; writing, within its
    `update` rules, since paying a document changes it. The payments themselves
    go through `PaymentService`, whose rules and movement booking apply as on any
    write.
    """

    payment_target_type: t.ClassVar[str]
    payment_target_field: t.ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        target_type = cls.__dict__.get("payment_target_type")
        if target_type is None:
            return  # an abstract intermediate class
        field_name = cls.__dict__.get("payment_target_field")
        try:
            field = Payment._meta.get_field(field_name or "")
        except Exception as exc:  # FieldDoesNotExist, or no name at all
            raise ImproperlyConfigured(
                f"{cls.__name__}.payment_target_field must name a foreign key of Payment."
            ) from exc
        # The field named after the target type: see `TARGET_FIELDS`.
        if field_name != target_type:
            raise ImproperlyConfigured(
                f"{cls.__name__}.payment_target_field must be {target_type!r}, the foreign "
                f"key named after its target type."
            )
        if not isinstance(field, models.ForeignKey) or field.related_model is not cls.model:
            raise ImproperlyConfigured(
                f"Payment.{field_name} is not a foreign key to {cls.model.__name__}."
            )
        if target_type in payment_target_registry:
            raise ImproperlyConfigured(
                f"Two services settle the target type {target_type!r}: "
                f"{payment_target_registry[target_type].__name__} and {cls.__name__}."
            )
        payment_target_registry[target_type] = cls

    # Hooks

    @classmethod
    def _payment_default_values(cls, target) -> t.Dict[str, t.Any]:
        return {}

    @classmethod
    def _payment_validate(cls, target, values: t.Dict[str, t.Any], instance) -> None:
        pass

    @classmethod
    def _payment_movement_values(cls, target, payment) -> t.Optional[t.Dict[str, t.Any]]:
        return None

    # Operations

    async def payment_read(self, target_pk, ordering=None, fields=None):
        """The payments of document `target_pk`, as an unevaluated queryset
        (see `ReadMixin.read`), ordered by `ordering` -- the latest first by
        default -- and loading `fields`.

        Raises the model's `DoesNotExist` if the document is out of reach.
        """
        target = await self._payment_target(target_pk, "read")
        return await self.env[Payment].read(
            {self.payment_target_field: target.pk, "state": PaymentState.DONE},
            ordering=ordering or ["-date", "-create_date"],
            fields=fields,
        )

    async def payment_register(self, target_pk, data: BaseModel) -> Payment:
        """Create a `done` payment of document `target_pk` from `data`, a schema of
        the payment fields without the target, the state nor the contact: forced,
        the contact by `_payment_default_values`.

        Raises the model's `DoesNotExist` if the document is out of reach.
        """
        target = await self._payment_target(target_pk)
        values = {
            **self._payment_default_values(target),
            **{name: getattr(data, name) for name in data.model_fields_set},
            "state": PaymentState.DONE,
            "target_type": self.payment_target_type,
            self.payment_target_field: target.pk,
        }
        [payment] = await self.env[Payment].create([PaymentCreateSchema(**values)])
        return payment

    async def payment_update(self, target_pk, payment_pk, data: BaseModel):
        """Update done payment `payment_pk` of document `target_pk` with `data`.
        Returns `(count, queryset)` as `update`: 0 when the payment is not a done
        one of this document's. Raises the model's `DoesNotExist` if the document
        is out of reach."""
        target = await self._payment_target(target_pk)
        return await self.env[Payment].update(
            self._payment_filters(target, payment_pk),
            PaymentUpdateSchema(**data.model_dump(exclude_unset=True)),
        )

    async def payment_cancel(self, target_pk, payment_pk) -> int:
        """Cancel done payment `payment_pk` of document `target_pk`: its movement
        goes, the payment stays. The count cancelled, 0 when it is not a done one
        of this document's. Raises the model's `DoesNotExist` if the document is
        out of reach."""
        target = await self._payment_target(target_pk)
        count, _queryset = await self.env[Payment].update(
            self._payment_filters(target, payment_pk), PaymentUpdateSchema(state=PaymentState.CANCELLED)
        )
        return count

    # Utils

    async def _payment_target(self, target_pk, operation="update"):
        queryset = await self.apply_access_rules(self.get_queryset(), operation)
        target = await queryset.filter(pk=target_pk).afirst()
        if target is None:
            raise self.model.DoesNotExist(f"{self.model._meta.verbose_name.capitalize()} not found.")
        return target

    def _payment_filters(self, target, payment_pk):
        return {"id": payment_pk, self.payment_target_field: target.pk, "state": PaymentState.DONE}
