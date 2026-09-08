from django.apps import AppConfig, apps

DEFAULT_WEBSITE_ID = "01M209K5BNS12QRPHXFWVJNVD1"


class WebsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "website"

    populate_dependencies = ["user"]
    populate_fixtures = ["user_roles", "page", "menu", "website"]

    def populate_system(self, size, **kwargs):
        Website = apps.get_model('website', 'Website')

        defaults = {
            "name": "My Website",
            "headline": "My Website Headline",
        }
        Website.objects.get_or_create(pk=DEFAULT_WEBSITE_ID, defaults=defaults)
