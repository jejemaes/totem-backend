from django.db import models
from django.utils import timezone

from core import fields
from website.models.mixins import WebsitePublishedMixin, WebsitePublishedQuerySet


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
    title = models.CharField(
        "Title", max_length=256, null=False, blank=False)
    content = fields.HtmlField(
        "Content", null=False, blank=False, help_text="HTML content")
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
