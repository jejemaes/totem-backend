from django.db.models import Q, Sum

from core.services import (
    CreateMixin,
    DeleteMixin,
    Dimension,
    GroupByMixin,
    Measure,
    ReadMixin,
    ResequenceMixin,
    ServiceBase,
    ServiceValidationError,
    ServiceValidationMultiError,
    UpdateMixin,
    date_dimensions,
    number_measures,
)
from account.models import AccountMovement
from payment.choices import PaymentDirection, PaymentMethodType, PaymentState, PaymentTargetType
from payment.models import Payment, PaymentMethod
from payment.schemas import (
    PaymentCreateSchema,
    PaymentMethodCreateSchema,
    PaymentMethodUpdateSchema,
    PaymentUpdateSchema,
)

from .mixins import PaymentTargetServiceMixin, payment_target_registry

# The foreign key of each target type, `{field name: target type}`: one per
# `PaymentTargetType`, named after it, as the `payment_target` constraint has it.
TARGET_FIELDS = {target_type: target_type for target_type in PaymentTargetType.values}

# What the rules of a document read of the payment, as it will be once written.
VALIDATED_FIELDS = ("amount", "currency_code", "direction", "state", "date", "contact")

DELETABLE_STATES = (PaymentState.DRAFT, PaymentState.CANCELLED)


class PaymentMethodService(
    CreateMixin[PaymentMethodCreateSchema],
    ReadMixin,
    UpdateMixin[PaymentMethodUpdateSchema],
    DeleteMixin,
    ResequenceMixin,
    ServiceBase[PaymentMethod],
):
    """Deleting a payment method used by a payment is refused by its `PROTECT`
    foreign key: deactivate it instead.

    The IBAN itself is checked by the validator of the field, and stored in its
    electronic form by `PaymentMethodQuerySet`.
    """

    def validate_data(self, data, instance):
        # A bank method has an IBAN, and only a bank one: also the
        # `payment_method_iban_bank` constraint, which names no field. Checked
        # when either side changes, the other one read from the record.
        if "type" in data or "iban" in data:
            method_type = data["type"] if "type" in data else instance.type
            iban = data["iban"] if "iban" in data else (instance.iban if instance is not None else None)
            if method_type == PaymentMethodType.BANK and not iban:
                raise self.ValidationError("A bank payment method needs an IBAN.", key="iban")
            if method_type != PaymentMethodType.BANK and iban:
                raise self.ValidationError("Only a bank payment method has an IBAN.", key="iban")


class PaymentService(
    CreateMixin[PaymentCreateSchema],
    ReadMixin,
    GroupByMixin,
    UpdateMixin[PaymentUpdateSchema],
    DeleteMixin,
    ServiceBase[Payment],
):
    """A payment settles at most one document, for its whole amount; a document
    may be settled by several payments, hence partially.

    What depends on the kind of document -- its rules, the movement it books -- is
    told by the document's service, found in `payment_target_registry` (see
    `PaymentTargetServiceMixin`). A `done` payment on a document books an account
    movement, which every write here keeps in step (`_sync_account_movements`), in
    the same transaction. Only a draft or
    a cancelled payment can be deleted: a done one has its money gone and its
    movement booked, a pending one is on its way. Cancel it first.
    """

    group_by_dimensions = {
        "payment_method": Dimension("payment_method"),
        "state": Dimension("state"),
        "direction": Dimension("direction"),
        "currency_code": Dimension("currency_code"),
        "contact": Dimension("contact"),
        "target_type": Dimension("target_type"),
        **date_dimensions("date", ["day", "week", "month", "quarter", "year"]),
    }
    group_by_measures = {
        **number_measures("amount", ["sum", "avg"]),
        # Signed by the direction: what the payments add up to for us.
        "net_sum": Measure(
            Sum("amount", filter=Q(direction=PaymentDirection.INCOMING), default=0)
            - Sum("amount", filter=Q(direction=PaymentDirection.OUTGOING), default=0),
            "amount",
            label="Net",
        ),
    }

    # What a payment write must change for its movement to follow.
    movement_source_fields = frozenset(
        {"state", "amount", "date", "direction", "target_type", *TARGET_FIELDS}
    )
    # Written when the movement is booked, then the movement's own: anyone may
    # edit them on the movement, and a later write of the payment leaves them be
    # -- nor does a later change of the document's default category. The others
    # -- amount, date, reference, account, origin -- stay the payment's, which
    # `AccountMovementService` protects.
    movement_initial_fields = frozenset({"name", "contact_id", "category_id"})

    def validate_data(self, data, instance):
        error = self.ValidationError({})

        def value(name):
            # The value the record will hold: written, or kept.
            if name in data:
                return data[name]
            if instance is not None:
                return getattr(instance, name)
            return Payment._meta.get_field(name).get_default()

        # Also a check constraint, which only reports an unkeyed integrity error.
        if "amount" in data and data["amount"] is not None and data["amount"] <= 0:
            error.add_message("The amount must be positive.", key="amount")

        method = data.get("payment_method")
        if method is not None and not method.active:
            error.add_message("This payment method is not active.", key="payment_method")

        # The target: the foreign key `target_type` names is set, the others not.
        # Also the `payment_target` constraint, which names no field.
        target_type = value("target_type")
        if "target_type" in data or any(field in data for field in TARGET_FIELDS):
            for field, kind in TARGET_FIELDS.items():
                if kind == target_type and value(field) is None:
                    error.add_message(f"A payment of a target {kind} needs one.", key=field)
                elif kind != target_type and value(field) is not None:
                    error.add_message(f"Only a payment of a target {kind} names one.", key=field)

        # The rules of the document settled, for its own service to tell.
        target_service = payment_target_registry.get(target_type) if target_type else None
        target = value(target_service.payment_target_field) if target_service else None
        if target is not None and not error:
            try:
                target_service._payment_validate(
                    target, {name: value(name) for name in VALIDATED_FIELDS}, instance
                )
            except ServiceValidationError as exc:
                for key, messages in exc.message_dict.items():
                    error.add_message(messages, key=key)

        if error:
            raise error

    def _create_postprocess(self, instances):
        self._sync_account_movements([instance.pk for instance in instances])
        return instances

    def _update_postprocess(self, queryset, update_values):
        if self.movement_source_fields & set(update_values):
            self._sync_account_movements(list(queryset.values_list("pk", flat=True)))

    def _delete_preprocess(self, queryset):
        # Reported as a `PROTECT` would be: the record itself refuses, not a field.
        if queryset.exclude(state__in=DELETABLE_STATES).exists():
            raise ServiceValidationMultiError(
                {"__all__": ServiceValidationError(
                    "Only a draft or a cancelled payment can be deleted: cancel it first."
                )},
                code="protected_error",
            )
        return queryset

    # Movements

    def _sync_account_movements(self, pks):
        """Create, rewrite or delete the movements of payments `pks`.

        A payment that is `done` and settles a document books the movement the
        document's service describes (`_payment_movement_values`), signed by the
        direction of the payment and dated by it; any other payment books none.
        Rewritten, a movement only follows what the payment owns: its name,
        contact and category (`movement_initial_fields`) are its own once booked.

        Written through the `AccountMovement` QuerySet and not through its
        service: a booked movement is derived data, the acting user need not hold
        the movement scopes to pay a document, and that service refuses to write
        the amount, date and reference of a movement with an origin anyway. Inside the computed-field context of
        the payment write, which this joins: the account and budget totals reading
        the movements are refreshed before it commits.
        """
        with self.env.computed_refresh() as computed:
            payments = list(
                Payment.objects.filter(pk__in=pks).select_related("account_movement", *TARGET_FIELDS)
            )

            to_delete = []
            to_create = []  # (payment, values)
            for payment in payments:
                values = self._movement_values(payment)
                movement = payment.account_movement
                if values is None:
                    if movement is not None:
                        to_delete.append(movement.pk)
                elif movement is None:
                    to_create.append((payment, values))
                else:
                    changed = {
                        name: value for name, value in values.items()
                        if name not in self.movement_initial_fields and getattr(movement, name) != value
                    }
                    if changed:
                        fields = {name.removesuffix("_id") for name in changed}
                        # A movement moved to another account leaves the totals of
                        # the first: captured before the write, see `_update_atomic`.
                        if computed.has_relation_to_modify(AccountMovement, fields):
                            computed.modified(AccountMovement, [movement.pk], fields, before=True)
                        AccountMovement.objects.filter(pk=movement.pk).update(**changed)
                        computed.modified(AccountMovement, [movement.pk], fields)

            if to_delete:
                queryset = AccountMovement.objects.filter(pk__in=to_delete)
                computed.deleted(queryset)
                # `Payment.account_movement` is `SET_NULL`: the link goes with it.
                queryset.delete()

            if to_create:
                movements = AccountMovement.objects.bulk_create(
                    [AccountMovement(**values) for _payment, values in to_create]
                )
                computed.created(movements)
                for (payment, _values), movement in zip(to_create, movements):
                    Payment.objects.filter(pk=payment.pk).update(account_movement=movement)

    @staticmethod
    def _movement_values(payment):
        """The values of the movement `payment` books, or None if it books none."""
        if payment.state != PaymentState.DONE or payment.target_type is None:
            return None
        target_service = payment_target_registry[payment.target_type]
        target = getattr(payment, target_service.payment_target_field)
        values = target_service._payment_movement_values(target, payment)
        if values is None:
            return None
        name = " ".join(filter(None, ["Payment", payment.reference]))
        if values.get("reference"):
            name = f"{name} - {values['reference']}"
        return {
            "name": name,
            **values,
            "amount": payment.amount if payment.direction == PaymentDirection.INCOMING else -payment.amount,
            "date": payment.date,
        }
