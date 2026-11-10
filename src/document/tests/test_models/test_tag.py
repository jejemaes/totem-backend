from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from document.models import DocumentTag, DocumentTagCategory
from document.tests.common import DocumentTestMixin


class TestDocumentTagModel(DocumentTestMixin, TestCase):

    def test_category_with_tags_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            DocumentTagCategory.objects.filter(pk=self.category_status.pk).delete()

    def test_name_is_unique_within_a_category(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentTag.objects.create(name="Draft", category=self.category_status)

    def test_same_name_in_another_category(self):
        DocumentTag.objects.create(name="Draft", category=self.category_year)

    def test_category_color_out_of_range_is_refused(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            DocumentTagCategory.objects.create(name="Realm", color=16)
