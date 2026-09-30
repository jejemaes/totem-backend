from django.db import models
from django.utils.translation import gettext_lazy as _
from ulid import ULID


def generate_ulid() -> str:
    """Module-level function, and not a lambda: a field default must stay
    importable for the migration serializer.
    """
    return str(ULID())


class ULIDField(models.CharField):
    """A 26-character Crockford base32 ULID, meant to be used as a primary key.

    A `CharField` and not a `UUIDField`, even though a ULID is also 128 bits: the
    whole point of a ULID over a UUID4 is that it reads and sorts in creation
    order, and both properties only survive in the canonical 26-char form. Stored
    as a `uuid` column, every API client would get `018f...-...` back instead.
    """

    description = _("ULID")

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 26)
        kwargs.setdefault("default", generate_ulid)
        kwargs.setdefault("editable", False)
        super().__init__(*args, **kwargs)
