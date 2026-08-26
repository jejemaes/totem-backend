from django.db import models


class Country(models.Model):
    code = models.CharField(
        "Code", max_length=2, null=False, blank=False, primary_key=True, help_text="ISO 3166-1 alpha-2 code.")
    name = models.CharField(
        "Name", max_length=255, null=False, blank=False)

    class Meta:
        verbose_name = "Country"
        verbose_name_plural = "Countries"
        constraints = [
            # A `CheckConstraint` and not a field validator: the service layer never
            # calls `full_clean()`, so django validators are only enforced through
            # their pydantic translation, at the API boundary. Anything writing
            # through the ORM (fixture, shell, admin, migration) only meets this.
            models.CheckConstraint(
                check=models.Q(code__regex=r"^[A-Z]{2}$"),
                name="country_code_iso_alpha2",
                violation_error_message="The country code must be 2 uppercase letters (ISO 3166-1 alpha-2).",
            ),
        ]

    def __str__(self):
        return self.name
