from core.services import CreateMixin, DeleteMixin, ReadMixin, ServiceBase, UpdateMixin
from contact.models import Contact, ContactTag
from contact.schemas import (
    ContactCreateSchema,
    ContactTagCreateSchema,
    ContactTagUpdateSchema,
    ContactUpdateSchema,
)


class ContactTagService(
    CreateMixin[ContactTagCreateSchema],
    ReadMixin,
    UpdateMixin[ContactTagUpdateSchema],
    DeleteMixin,
    ServiceBase[ContactTag],
):
    pass


class ContactService(
    CreateMixin[ContactCreateSchema],
    ReadMixin,
    UpdateMixin[ContactUpdateSchema],
    DeleteMixin,
    ServiceBase[Contact],
):
    pass
