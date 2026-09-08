from django.db import models

from core.orm import fields


class Website(models.Model):
    id = fields.ULIDField("ID", primary_key=True)
    name = models.CharField(
        "Name", max_length=256, null=False, blank=False
    )
    headline = models.CharField(
        "Headline", max_length=256, null=False, blank=False
    )

    meta_authors = models.CharField("Meta Author", max_length=256, null=True, blank=True)
    meta_description = models.TextField("Meta Description", null=True, blank=True)

    menu = models.ForeignKey('website.Menu', verbose_name="Main Menu", null=True, blank=True, on_delete=models.SET_NULL, help_text="Parent item as the main menu of the website.")
    # `PROTECT`, like `Menu.page`: the page the site opens on should not be
    # deletable out from under it. Nullable because a freshly provisioned system
    # has no content yet -- which is why `/` must degrade rather than 404.
    homepage = models.ForeignKey('website.Page', verbose_name="Homepage", null=True, blank=True, on_delete=models.PROTECT, related_name="+", help_text="Page rendered at the root of the website.")

    footer = fields.HtmlField("Footer Content", null=True, blank=True, allow_widget=True)

    class Meta:
        verbose_name = "Website"
        verbose_name_plural = "Websites"
