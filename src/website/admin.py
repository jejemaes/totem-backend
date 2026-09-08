from django.contrib import admin
from django import forms

from website.models import Page, Media, Menu, Website


# -------------------------------------
# Media
# -------------------------------------

class MediaAdminForm(forms.ModelForm):

    class Meta:
            model = Media
            fields = ('content',)

    def clean(self):
        if self.instance._state.adding: # creation flow
            memory_file = self.cleaned_data.get('content') # InMemoryUploadedFile or _io.BufferedRandom

            if memory_file:
                values = Media.precompute_values(memory_file.read(), memory_file.name)
                self.cleaned_data.update(values)

        return super().clean()

    def save(self, commit=True):
        for field in self.cleaned_data:
            setattr(self.instance, field, self.cleaned_data.get(field))
        return super().save(commit=commit)


class MediaAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "mimetype")
    readonly_fields = ["checksum", "mimetype", "content"]

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj=obj)
        if obj is None:
            if 'content' in fields:
                fields.remove('content')
        return fields

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if object_id is None:
            self.form = MediaAdminForm
        else:
            self.form = forms.ModelForm # default
        return super().changeform_view(request, object_id=object_id, form_url=form_url, extra_context=extra_context)



admin.site.register(Media, MediaAdmin)


# -------------------------------------
# Website Page
# -------------------------------------

class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published")


admin.site.register(Page, PageAdmin)


# -------------------------------------
# Website Menu
# -------------------------------------

class MenuAdmin(admin.ModelAdmin):
    list_display = ("name", "sequence", "page", "link")


admin.site.register(Menu, MenuAdmin)


# -------------------------------------
# Website
# -------------------------------------

class WebsiteAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "headline")


admin.site.register(Website, WebsiteAdmin)
