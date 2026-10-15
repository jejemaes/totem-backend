from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.orm.fields import ULIDField


class AccountCategory(models.Model):
    id = ULIDField("ID", primary_key=True)
    name = models.CharField("Name", max_length=100)
    color = models.PositiveSmallIntegerField(
        "Color",
        default=0,
        # As `ContactTag.color`: the validators land in the request schemas, the
        # check constraint covers the ORM side.
        validators=[MinValueValidator(0), MaxValueValidator(15)],
        help_text="Index in the front-end color palette.",
    )
    account = models.ForeignKey(
        "account.Account",
        verbose_name="Account",
        related_name="categories",
        null=True,
        blank=True,
        # A category scoped to an account has no meaning without it.
        on_delete=models.CASCADE,
        help_text="Empty for a general category, usable on the movements of any account.",
    )

    class Meta:
        verbose_name = "Account Category"
        verbose_name_plural = "Account Categories"
        constraints = [
            # Two conditional constraints rather than one with `nulls_distinct=False`,
            # which needs PostgreSQL 15: the database runs 14.
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(account__isnull=True),
                name="unique_account_category_general_name",
                violation_error_message="A general category with that name already exists.",
            ),
            models.UniqueConstraint(
                fields=["account", "name"],
                condition=models.Q(account__isnull=False),
                name="unique_account_category_account_name",
                violation_error_message="This account already has a category with that name.",
            ),
            models.CheckConstraint(
                condition=models.Q(color__gte=0, color__lte=15),
                name="account_category_color_range",
                violation_error_message="The color must be between 0 and 15.",
            ),
        ]

    def __str__(self):
        return self.name
