from django.db import models
from django.utils import timezone

from core.orm import fields
from website.models.mixins import WebsitePublishedMixin, WebsitePublishedQuerySet
from website.theme import LAYOUT_DEFAULT, get_layout_choices


class PageQuerySet(WebsitePublishedQuerySet):

    def update(self, **kwargs):
        # `auto_now` lives in `DateTimeField.pre_save()`, which only runs on
        # `Model.save()` and on inserts. The service layer writes updates
        # through `queryset.update()` (`core.services.mixins.UpdateMixin`), so
        # without this the field would never move after creation. Same reason as
        # `ContactQuerySet.update`.
        kwargs.setdefault("update_date", timezone.now())
        return super().update(**kwargs)


class Page(WebsitePublishedMixin):
    id = fields.ULIDField("ID", primary_key=True)
    title = models.CharField(
        "Title", max_length=256, null=False, blank=False)
    content = fields.HtmlField(
        "Content", null=False, blank=False, allow_widget=True, help_text="HTML content")
    # `choices` here, and NOT on `Website.theme` -- write the contrast down in
    # both places, because the next person will otherwise "harmonise" the two
    # fields and break one of them. What differs is where the vocabulary comes
    # from: `LAYOUTS` is a module constant, complete on import, so the callable
    # is safe whenever `core.schemas.fields` evaluates it and gives the editor a
    # real enum in the OpenAPI schema plus an admin dropdown for free. A theme
    # id comes from a registry, and an enum on the read path would make a stale
    # stored value unserializable instead of degrading.
    #
    # A callable, so django serializes it into the migration as an import
    # reference and adding a layout generates none.
    #
    # Not nullable: `NULL` and `"full-width"` would be two spellings of the same
    # thing, forcing a coalesce at every read site -- template resolution
    # included. Non-null with a default also means the migration needs no data
    # step.
    layout = models.CharField(
        "Layout",
        max_length=64,
        null=False,
        blank=False,
        default=LAYOUT_DEFAULT,
        choices=get_layout_choices,
        help_text=(
            "Structure of the page body. Layout ids are a vocabulary shared by "
            "every theme; a theme that does not implement one falls back when "
            "the page renders, which is why switching theme cannot invalidate a "
            "page."
        ),
    )
    update_date = models.DateTimeField("Update Date", auto_now=True)
    user = models.ForeignKey('user.User', verbose_name="Author", null=True, blank=True, on_delete=models.SET_NULL, help_text="Author of the web page.")

    objects = PageQuerySet.as_manager()

    @property
    def url(self):
        return f"/page/{self.slug}/"

    class Meta(WebsitePublishedMixin.Meta):
        verbose_name = "Page"
        verbose_name_plural = "Pages"
        constraints = WebsitePublishedMixin.Meta.constraints

    def __str__(self):  # pylint: disable=E0307
        return self.title
