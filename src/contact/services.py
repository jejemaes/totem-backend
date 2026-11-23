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
    """A person or a company.

    Which fields a contact may fill depends on its type. The check constraint of
    the model holds the line, but only reports an unkeyed integrity error: the
    rules are restated here to name the faulty field. That the parent is a company
    has no constraint at all, since it reads another row.
    """

    # Filled by a person only, and by a company only.
    PERSON_FIELDS = ("first_name", "last_name", "birth_date", "parent")
    COMPANY_FIELDS = ("name", "vat")

    def validate_data(self, data, instance):
        error = self.ValidationError({})

        # An update only carries the fields it changes: the others are read from
        # the record. Relations arrive resolved, as instances.
        def value(field_name):
            if field_name in data:
                return data[field_name]
            if instance is None:
                return None
            if field_name == "parent":
                return instance.parent_id  # costs no query
            return getattr(instance, field_name)

        is_company = value("is_company") or False

        if is_company:
            for field_name in self.PERSON_FIELDS:
                # `is not None`, blank included: the constraint wants NULL.
                if value(field_name) is not None:
                    error.add_message("A company cannot have this field.", key=field_name)
            # Blank too: `blank=True` only because a person has none.
            if not value("name"):
                error.add_message("A company must have a name.", key="name")
        else:
            for field_name in self.COMPANY_FIELDS:
                if value(field_name) is not None:
                    error.add_message("A person cannot have this field.", key=field_name)
            if not value("last_name"):
                error.add_message("A person must have a last name.", key="last_name")

            parent = data.get("parent")
            if parent is not None:
                if not parent.is_company:
                    error.add_message("The parent must be a company.", key="parent")
                elif instance is not None and parent.pk == instance.pk:
                    error.add_message("A contact cannot be its own company.", key="parent")

        # A company turned into a person would leave its persons under a person.
        # Only when the type changes: the query is not worth it otherwise.
        if (
            instance is not None
            and instance.is_company
            and not is_company
            and instance.children.exists()
        ):
            error.add_message(
                "This company still has contacts: detach them first.", key="is_company"
            )

        if error:
            raise error
