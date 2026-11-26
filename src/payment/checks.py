from django.core.checks import Error, register

from payment.choices import PaymentTargetType


@register()
def check_payment_targets(app_configs, **kwargs):
    """Every target type has a service telling its rules and its movement.

    A system check rather than a test in `ready()`: the services register
    their target type when `core` autodiscovers them, after every `ready()`.
    Without one, the first payment of that type would fail on a missing key.
    """
    from payment.services.mixins import payment_target_registry

    return [
        Error(
            f"No service settles the payment target type {target_type!r}.",
            hint="Compose PaymentTargetServiceMixin in the service of its documents.",
            id="payment.E001",
        )
        for target_type in PaymentTargetType.values
        if target_type not in payment_target_registry
    ]
