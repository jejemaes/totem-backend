import uuid

from django.db import models

from core import fields


class Website(models.Model):
    id = models.UUIDField(
        default=uuid.uuid4, editable=False, null=False, primary_key=True
    )
    name = models.CharField(
        "Name", max_length=256, null=False, blank=False
    )
    headline = models.CharField(
        "Headline", max_length=256, null=False, blank=False
    )

    meta_authors = models.CharField("Meta Author", max_length=256, null=True, blank=True)
    meta_description = models.TextField("Meta Description", null=True, blank=True)

    menu = models.ForeignKey('website.Menu', verbose_name="Main Menu", null=True, blank=True, on_delete=models.SET_NULL, help_text="Parent item as the main menu of the website.")

    footer = fields.HtmlField("Footer Content", null=True, blank=True)

    class Meta:
        verbose_name = "Website"
        verbose_name_plural = "Websites"
