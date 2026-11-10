from django.contrib import admin

from document.models import Document, DocumentTag, DocumentTagCategory

# The admin writes through `Model.save()`, around the service layer: the checks
# of `DocumentService.validate_data` do not run here. The type/content rule
# still holds, as a constraint of the model.


@admin.register(DocumentTagCategory)
class DocumentTagCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "sequence", "color")
    search_fields = ("name",)


@admin.register(DocumentTag)
class DocumentTagAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "sequence")
    list_filter = ("category",)
    search_fields = ("name",)


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "document_type", "mimetype", "size", "date", "user", "contact", "create_date")
    list_filter = ("document_type", "tags")
    search_fields = ("name",)
    raw_id_fields = ("contact",)
    filter_horizontal = ("tags",)
    # Metadata only. The type and the file are fixed at creation, and the text
    # too here: `Model.save()` would not refresh its `size`, which only
    # `DocumentQuerySet.update` follows.
    readonly_fields = (
        "document_type", "file", "thumbnail", "text_content", "mimetype", "checksum", "size",
        "create_date", "update_date",
    )

    def has_add_permission(self, request):
        # `mimetype`, `checksum` and `size` are derived by `DocumentService` at
        # creation: a document created through `Model.save()` would have none.
        return False
