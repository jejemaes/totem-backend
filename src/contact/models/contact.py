from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce, Concat, Lower, Trim
from django.utils import timezone

from base.models.mixins import AddressMixin
from core.orm.fields import ComputedField, ULIDField


class ContactQuerySet(models.QuerySet):

    def update(self, **kwargs):
        # `auto_now` lives in `DateTimeField.pre_save()`, which only runs on
        # `Model.save()`. The service layer writes updates through
        # `queryset.update()` (`core.services.mixins.UpdateMixin._update_atomic`),
        # so without this the field would never move after creation.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class Contact(AddressMixin):
    """A person or a company, in one table.

    One table rather than a `Company` model of its own: every relation to a contact
    (`AccountMovement.contact`, `Document.contact`) may point at either, and the
    address, email, tags, API and scopes are shared. What differs between the two
    is a handful of columns left NULL on one side, which the check constraint below
    pins down.
    """

    id = ULIDField("ID", primary_key=True)
    is_company = models.BooleanField(
        "Is a Company",
        default=False,
        help_text="A company has a name and a VAT number; a person has a first and "
        "a last name, and may belong to a company.",
    )
    # Persons only.
    first_name = models.CharField(
        "First name", max_length=255, null=True, blank=True)
    # Required of a person, but nullable: a company has none. The check constraint
    # enforces it, a `blank=False` alone would refuse the NULL of a company.
    last_name = models.CharField(
        "Last name", max_length=255, null=True, blank=True)
    # Companies only. Not `last_name` reused: a company has no last name, and a
    # person's search or ordering by last name must not mix company names in.
    name = models.CharField(
        "Name", max_length=255, null=True, blank=True,
        help_text="Name of the company.")
    vat = models.CharField(
        "VAT Number", max_length=32, null=True, blank=True)
    # `SET_NULL`: deleting a company leaves its employees in the address book.
    # That the parent is a company is not expressible as a check constraint, which
    # only reads its own row: `ContactService.validate_data` enforces it.
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        limit_choices_to={"is_company": True},
        verbose_name="Company",
        help_text="Company the person belongs to.",
    )
    # Reads its own row only, so `ComputedField` returns a `GeneratedField`:
    # PostgreSQL keeps it in sync on every write, `queryset.update()` included,
    # and persons and companies list, search and sort on one column. `Trim`: a
    # person without first name would otherwise start with a space.
    display_name = ComputedField(
        "Display Name",
        output_field=models.CharField(max_length=511),
        annotation_method=lambda: Coalesce(
            F("name"), Trim(Concat(F("first_name"), Value(" "), F("last_name")))
        ),
        depends_on=["name", "first_name", "last_name"],
        stored=True,
        help_text="The name of a company, the first and last names of a person.",
    )
    email = models.EmailField(
        "Email", max_length=255, null=True, blank=True)
    mobile = models.CharField(
        "Mobile", max_length=32, null=True, blank=True)
    birth_date = models.DateField(
        "Birth date", null=True, blank=True)
    tags = models.ManyToManyField(
        'contact.ContactTag', related_name='contacts', blank=True)

    create_date = models.DateTimeField("Create Date", auto_now_add=True)
    update_date = models.DateTimeField("Update Date", auto_now=True)

    objects = ContactQuerySet.as_manager()

    class Meta:
        verbose_name = "Contact"
        verbose_name_plural = "Contacts"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        is_company=True,
                        name__isnull=False,
                        first_name__isnull=True,
                        last_name__isnull=True,
                        birth_date__isnull=True,
                        parent__isnull=True,
                    )
                    | Q(
                        is_company=False,
                        last_name__isnull=False,
                        name__isnull=True,
                        vat__isnull=True,
                    )
                ),
                name="contact_person_or_company",
                violation_error_message="A company has a name and no parent; a person "
                "has a last name and no company name nor VAT number.",
            ),
            models.CheckConstraint(
                condition=~Q(parent=F("id")),
                name="contact_parent_not_self",
                violation_error_message="A contact cannot be its own company.",
            ),
            # Partial: most contacts have no VAT number. On `Lower(vat)` for the
            # same reason as the tag names: "be0123" next to "BE0123" is one company.
            models.UniqueConstraint(
                Lower("vat"),
                condition=Q(vat__isnull=False),
                name="unique_contact_vat",
                violation_error_message="A company with that VAT number already exists.",
            ),
        ]

    def __str__(self):
        if self.is_company:
            return self.name
        if self.first_name:
            return f"{self.first_name} {self.last_name}"
        return self.last_name
