from django.db import models
from django.utils import timezone

from base.models.mixins import AddressMixin
from core.orm.fields import ULIDField


class ContactQuerySet(models.QuerySet):

    def update(self, **kwargs):
        # `auto_now` lives in `DateTimeField.pre_save()`, which only runs on
        # `Model.save()`. The service layer writes updates through
        # `queryset.update()` (`core.services.mixins.UpdateMixin._update_atomic`),
        # so without this the field would never move after creation.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class Contact(AddressMixin):
    id = ULIDField("ID", primary_key=True)
    first_name = models.CharField(
        "First name", max_length=255, null=True, blank=True)
    last_name = models.CharField(
        "Last name", max_length=255, null=False, blank=False)
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

    def __str__(self):
        if self.first_name:
            return f"{self.first_name} {self.last_name}"
        return self.last_name
