from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.orm.fields import ULIDField


class ContactTag(models.Model):
    id = ULIDField("ID", primary_key=True)
    name = models.CharField(
        "Name", max_length=255, null=False, blank=False)
    color = models.PositiveSmallIntegerField(
        "Color",
        default=0,
        # `convert_validators` turns these into the `ge`/`le` of the generated
        # pydantic field, so the bound also lands in the request schemas and in
        # the OpenAPI document. The check constraint below covers the ORM side,
        # which never runs `full_clean()`.
        validators=[MinValueValidator(0), MaxValueValidator(15)],
        help_text="Index in the front-end color palette.",
    )

    class Meta:
        verbose_name = "Contact Tag"
        verbose_name_plural = "Contact Tags"
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="unique_contact_tag_name",
                violation_error_message="A tag with that name already exists.",
            ),
            models.CheckConstraint(
                check=models.Q(color__gte=0, color__lte=15),
                name="contact_tag_color_range",
                violation_error_message="The color must be between 0 and 15.",
            ),
        ]

    def __str__(self):
        return self.name
