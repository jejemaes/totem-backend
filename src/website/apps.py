from django.apps import AppConfig, apps

DEFAULT_WEBSITE_ID = "7a49103e-c0a8-4b24-af4f-fbced54c0263"


class WebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "website"

    populate_dependencies = ["user"]
    populate_fixtures = ["page", "menu", "website"]

    def populate_system(self, size, **kwargs):
        Website = apps.get_model('website', 'Website')

        defaults = {
            "name": "My Website",
            "headline": "My Website Headline",
        }
        Website.objects.get_or_create(pk=DEFAULT_WEBSITE_ID, defaults=defaults)
