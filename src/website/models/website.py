from django.core.exceptions import ValidationError
from django.db import models
from pydantic import ValidationError as PydanticValidationError

from core.orm import fields
from website.theme import DEFAULT_THEME_ID, get_theme, get_themes


class WebsiteQuerySet(models.QuerySet):

    def update(self, **kwargs):
        # A theme switch invalidates the stored options: they are keyed by the
        # option names of ONE `option_schema`, and nothing maps them onto
        # another theme's. Here and not in `WebsiteService.validate_data`,
        # because a validator that writes is what `MediaService`'s docstring
        # warns against, and because reacting to the mere *presence* of a field
        # in the payload is the same shape as `WebsitePublishedQuerySet.update`
        # restamping `date_published`.
        #
        # `setdefault`, so options sent in the same request still win.
        #
        # The admin writes through `Model.save()` and so never reaches this;
        # `WebsiteAdminForm.clean` carries the same rule, the way
        # `WebsitePublishedMixin` covers both writers.
        if "theme" in kwargs:
            kwargs.setdefault("theme_options", {})
        return super().update(**kwargs)


class Website(models.Model):
    id = fields.ULIDField("ID", primary_key=True)
    name = models.CharField(
        "Name", max_length=256, null=False, blank=False
    )
    headline = models.CharField(
        "Headline", max_length=256, null=False, blank=False
    )

    meta_authors = models.CharField("Meta Author", max_length=256, null=True, blank=True)
    meta_description = models.TextField("Meta Description", null=True, blank=True)

    menu = models.ForeignKey('website.Menu', verbose_name="Main Menu", null=True, blank=True, on_delete=models.SET_NULL, help_text="Parent item as the main menu of the website.")
    # `PROTECT`, like `Menu.page`: the page the site opens on should not be
    # deletable out from under it. Nullable because a freshly provisioned system
    # has no content yet -- which is why `/` must degrade rather than 404.
    homepage = models.ForeignKey('website.Page', verbose_name="Homepage", null=True, blank=True, on_delete=models.PROTECT, related_name="+", help_text="Page rendered at the root of the website.")

    footer = fields.HtmlField("Footer Content", null=True, blank=True, allow_widget=True)

    # No `choices`, deliberately, even though the registry is complete by the
    # time schemas are built (`WebsiteConfig.ready()` runs before
    # `CoreConfig.ready()`). `core.schemas.fields` turns `choices` into a
    # pydantic `Enum`, and that enum would land in the *response* schema too:
    # reading a website whose stored theme has since been deleted from the code
    # would then fail serialization instead of degrading. The whole point of
    # `WebsiteRenderContextMixin.get_theme` and `resolve_options` is that a
    # stale selection renders the default and logs. Validation lives in
    # `WebsiteService.validate_data`, which is also where the cross-field rule
    # with `theme_options` has to be anyway. An admin dropdown comes from
    # `get_theme_choices()` at form level -- see `WebsiteAdminForm`.
    theme = models.CharField(
        "Theme",
        max_length=64,
        null=False,
        blank=False,
        default=DEFAULT_THEME_ID,
        help_text=(
            "Identifier of the theme the website is rendered with. A theme is "
            "code, not a row: see `website.theme`. Only the selection is stored."
        ),
    )
    # `default=dict` and never `default={}`: a shared mutable would be the same
    # object on every instance.
    theme_options = models.JSONField(
        "Theme Options",
        null=False,
        blank=True,
        default=dict,
        help_text=(
            "Values for the options the selected theme declares in its "
            "`option_schema`. Holds the author's explicit overrides only: an "
            "option left unset falls back to the schema default when the page "
            "renders, so a theme adding an option needs no data migration."
        ),
    )

    objects = WebsiteQuerySet.as_manager()

    def clean(self):
        """The same two rules as `WebsiteService.validate_data`, for the admin.

        The admin writes through `Model.save()`, so the service hook never runs
        there -- the two-writer situation `WebsitePublishedMixin` already
        handles. The rule itself is not duplicated: both sides call
        `theme.validate_options` and each translates the pydantic error into its
        own layer's, exactly as `AbstractHtmlWidget.validate_attributes`
        prescribes. Being on the model means a hand-written ModelForm elsewhere
        cannot bypass it either.
        """
        super().clean()

        theme = get_theme(self.theme)
        if theme is None:
            raise ValidationError({
                "theme": (
                    f"{self.theme!r} is not a known theme. Available: "
                    f"{', '.join(t.id for t in get_themes()) or 'none'}."
                )
            })

        try:
            theme.validate_options(self.theme_options)
        except PydanticValidationError as exc:
            raise ValidationError({
                "theme_options": [
                    f"{'.'.join(str(p) for p in err['loc']) or '__all__'}: {err['msg']}"
                    for err in exc.errors()
                ]
            }) from exc

    class Meta:
        verbose_name = "Website"
        verbose_name_plural = "Websites"
