from django.db import models
from django.utils import timezone


class WebsitePublishedQuerySet(models.QuerySet):
    """`date_published` upkeep for the write paths that never call `save()`.

    `WebsitePublishedMixin.save()` stamps the field, but the service layer calls
    neither `save()` (it inserts with `bulk_create`) nor its `update_fields`
    branch (it writes with `queryset.update()`). Both are compensated here
    rather than in the service, so the admin, a script and the service share one
    definition of "publishing stamps the publication date".
    """

    def bulk_create(self, objs, *args, **kwargs):
        objs = list(objs)
        now = timezone.now()
        for obj in objs:
            if obj.is_published and obj.date_published is None:
                obj.date_published = now
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        # The mere presence of `is_published` in the payload restamps, which is
        # what `save()` does with `update_fields`. `setdefault` so an explicit
        # value still wins, even though no write schema exposes the field.
        if "is_published" in kwargs:
            kwargs.setdefault("date_published", timezone.now())
        return super().update(**kwargs)


class WebsitePublishedMixin(models.Model):
    slug = models.SlugField(
        "Slug",
        max_length=256,
        null=False,
        blank=False,
        help_text="URL part identifying the page."
    )
    is_published = models.BooleanField(
        "Is Published", null=False, blank=False, default=False, help_text="Is published on the website.")
    date_published = models.DateTimeField(
        "Publication Date", null=True, blank=True, help_text="Date of the last publication of the document.")

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=['slug'],
                name='%(class)s_unique_slug',
                violation_error_message="A document with that slug already exists.",
            ),
        ]

    def save(
        self, force_insert=False, force_update=False, using=None, update_fields=None
    ):
        if self._state.adding:
            # Creating something already published is a publication too. Without
            # this branch the admin leaves `date_published` empty, while
            # `WebsitePublishedQuerySet.bulk_create` stamps it -- two write paths
            # disagreeing about the same field.
            if self.is_published and self.date_published is None:
                self.date_published = timezone.now()
        elif update_fields and 'is_published' in update_fields:
            self.date_published = timezone.now()
            update_fields.append('date_published')
        return super().save(force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields)
