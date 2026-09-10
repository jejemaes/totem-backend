from django.apps import AppConfig, apps
from django.utils.module_loading import autodiscover_modules

DEFAULT_WEBSITE_ID = "01M209K5BNS12QRPHXFWVJNVD1"


class WebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "website"

    populate_dependencies = ["user"]
    populate_fixtures = ["user_roles", "page", "menu", "website"]

    def ready(self):
        # The theme classes any app contributes, keyed by id in `website.theme`.
        # Swept from here and not from `CoreConfig.ready()` -- where the sibling
        # `api` / `html_widget` / `services` sweeps live -- because
        # `validate_themes()` has to run after the sweep, and calling it from
        # `core` would make `core` import `website`. A theme is website-domain
        # vocabulary; `core` gains no notion of it.
        #
        # Safe despite `website` not being last in `INSTALLED_APPS`:
        # `autodiscover_modules` imports modules directly and does not depend on
        # another app's `ready()` having run, so an `event/theme.py` is found
        # even though `event` would be listed after this app. What it does
        # require is that `website.theme` import no model, which its docstring
        # states.
        autodiscover_modules("theme")

        from website.theme import validate_themes

        validate_themes()

    def populate_system(self, size, **kwargs):
        Website = apps.get_model('website', 'Website')

        defaults = {
            "name": "My Website",
            "headline": "My Website Headline",
        }
        Website.objects.get_or_create(pk=DEFAULT_WEBSITE_ID, defaults=defaults)
