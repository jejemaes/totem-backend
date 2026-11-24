from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from website.schemas import WebsiteUpdateSchema


class WebsiteSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("a script in the footer", {"footer": "<script>alert(1)</script>"}, "footer"),
            ("homepage too long for a ulid", {"homepage": "0" * 27}, "homepage"),
        ]
    )
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            WebsiteUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_update_schema_takes_any_theme(self):
        # No `choices` on `Website.theme`, on purpose: an enum would make a stale
        # stored value unserializable. The service checks the theme exists.
        self.assertEqual(WebsiteUpdateSchema(theme="isengard").theme, "isengard")

    def test_a_widget_marker_is_accepted_in_the_footer(self):
        footer = '<div><t-widget name="last-page" attrs=\'{"limit":5}\'/></div>'

        self.assertEqual(WebsiteUpdateSchema(footer=footer).footer, footer)
