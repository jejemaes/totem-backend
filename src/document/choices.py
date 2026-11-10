from django.db import models


class DocumentType(models.TextChoices):
    FILE = "file", "File"
    TEXT = "text", "Text"
