from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.orm.fields import ULIDField


class DocumentTagCategory(models.Model):
    """A family of tags (« Status », « Year », « Supplier »...).

    Documents are sorted by tags only, there is no folder: the category is what
    gives the tags a structure.
    """

    id = ULIDField("ID", primary_key=True)
    name = models.CharField("Name", max_length=255)
    sequence = models.IntegerField("Sequence", default=10)
    color = models.PositiveSmallIntegerField(
        "Color",
        default=0,
        # As `ContactTag.color`: the validators land in the request schemas, the
        # check constraint covers the ORM side.
        validators=[MinValueValidator(0), MaxValueValidator(15)],
        help_text="Index in the front-end color palette, shared by the tags of the category.",
    )

    class Meta:
        verbose_name = "Document Tag Category"
        verbose_name_plural = "Document Tag Categories"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="unique_document_tag_category_name",
                violation_error_message="A tag category with that name already exists.",
            ),
            models.CheckConstraint(
                condition=models.Q(color__gte=0, color__lte=15),
                name="document_tag_category_color_range",
                violation_error_message="The color must be between 0 and 15.",
            ),
        ]

    def __str__(self):
        return self.name
