from django.contrib import admin
from django import forms

from website.models import Page, Media, Menu, Website
from website.theme import get_theme_choices


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
    # `layout` needs no form of its own: the field carries `choices`, so django
    # renders the dropdown by itself. That is the one practical difference with
    # `Website.theme` -- see `WebsiteAdminForm`.
    list_display = ("title", "slug", "layout", "is_published")


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

class WebsiteAdminForm(forms.ModelForm):
    """The theme dropdown, and the options reset the queryset cannot do here.

    Two jobs the model field cannot do on its own.

    The dropdown: `theme` carries no `choices`, because they would become a
    pydantic `Enum` in the API *response* schema and a stored theme since
    deleted from the code would stop being serializable instead of degrading.
    Built here instead, per request, long after the registry is filled -- which
    is also why it cannot be a `choices` callable on the field.

    The reset: the admin writes through `Model.save()`, so
    `WebsiteQuerySet.update` never runs and its "a theme switch clears the
    stored options" rule would be silently missing. The same two-writer
    situation `WebsitePublishedMixin` handles, and the same answer.

    Validation itself is not duplicated -- `Website.clean()` owns it, and both
    the service and this form end up calling `theme.validate_options`.
    Precedent: `MediaAdminForm.clean`.
    """

    class Meta:
        model = Website
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["theme"] = forms.ChoiceField(
            choices=get_theme_choices(),
            label=Website._meta.get_field("theme").verbose_name,
            help_text=Website._meta.get_field("theme").help_text,
        )

    def clean(self):
        cleaned_data = super().clean()
        if "theme" in self.changed_data:
            # Not `cleaned_data["theme"] != self.instance.theme`:
            # `self.instance` has already been mutated by `_post_clean` on an
            # edit, so it no longer holds the stored value. `changed_data`
            # compares against the form's initial, which does.
            cleaned_data["theme_options"] = {}
            self.instance.theme_options = {}
        return cleaned_data


class WebsiteAdmin(admin.ModelAdmin):
    form = WebsiteAdminForm
    list_display = ("id", "name", "headline", "theme")

    def has_add_permission(self, request):
        # One row, provisioned by `populate_system`. A second one would make
        # `WebsiteService.read_current()` pick between two identities by pk
        # order.
        return not Website.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # Deleting the only row takes `/` down.
        return False


admin.site.register(Website, WebsiteAdmin)
