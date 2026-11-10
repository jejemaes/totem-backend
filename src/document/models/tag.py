from django.db import models

from core.orm.fields import ULIDField


class DocumentTag(models.Model):
    """A tag always belongs to a category (optional in Odoo).

    No `color` of its own: the tag shows the color of its category, which the
    read schema nests rather than this model copying it.
    """

    id = ULIDField("ID", primary_key=True)
    name = models.CharField("Name", max_length=255)
    category = models.ForeignKey(
        "document.DocumentTagCategory",
        verbose_name="Category",
        related_name="tags",
        # Not CASCADE: deleting a category would silently take its tags, and
        # with them their links to the documents.
        on_delete=models.PROTECT,
    )
    sequence = models.IntegerField(
        "Sequence", default=10, help_text="Order of the tag within its category."
    )

    class Meta:
        verbose_name = "Document Tag"
        verbose_name_plural = "Document Tags"
        constraints = [
            models.UniqueConstraint(
                fields=["category", "name"],
                name="unique_document_tag_name_per_category",
                violation_error_message="This category already has a tag with that name.",
            ),
        ]

    def __str__(self):
        return self.name
