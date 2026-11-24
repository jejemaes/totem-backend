from django.test import SimpleTestCase
from parameterized import parameterized
from pydantic import ValidationError as PydanticValidationError

from website.schemas import PageCreateSchema, PageUpdateSchema
from website.theme import LAYOUT_DEFAULT

PAYLOAD = {"title": "Bree", "slug": "bree", "content": "<p>The Prancing Pony</p>"}


class PageSchemaTest(SimpleTestCase):

    @parameterized.expand(
        [
            ("title missing", {"title": None}, "title"),
            ("not a slug", {"slug": "the prancing pony"}, "slug"),
            ("a script in the content", {"content": "<script>alert(1)</script>"}, "content"),
            # Inline parameters are validated when the *page* is written: the field
            # validator becomes a pydantic one through `convert_validators`.
            ("widget attrs not json", {"content": '<div><t-widget name="x" attrs="nope"/></div>'}, "content"),
            ("widget name absent", {"content": "<div><t-widget/></div>"}, "content"),
            ("a widget inside a widget", {"content": '<div><t-widget name="a"><t-widget name="b"/></t-widget></div>'}, "content"),
            ("author not a uuid", {"user": "frodon"}, "user"),
        ]
    )
    def test_create_schema_invalid(self, label, values, field):
        payload = {key: value for key, value in {**PAYLOAD, **values}.items() if value is not None}

        with self.assertRaises(PydanticValidationError) as ctx:
            PageCreateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    def test_create_schema_unknown_layout(self):
        # `choices` become a pydantic `Enum`: the message already names every
        # valid id, better than anything a service hook would write.
        with self.assertRaises(PydanticValidationError) as ctx:
            PageCreateSchema(**PAYLOAD, layout="no-such-layout")

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], ["layout"])
        self.assertIn(LAYOUT_DEFAULT, str(ctx.exception))

    @parameterized.expand(
        [
            ("layout set to null", {"layout": None}, "layout"),
            ("not a slug", {"slug": "the prancing pony"}, "slug"),
        ]
    )
    def test_update_schema_invalid(self, label, payload, field):
        with self.assertRaises(PydanticValidationError) as ctx:
            PageUpdateSchema(**payload)

        self.assertEqual([error["loc"][0] for error in ctx.exception.errors()], [field])

    @parameterized.expand([(PageCreateSchema,), (PageUpdateSchema,)])
    def test_derived_dates_are_on_no_write_schema(self, schema):
        # Kept by `PageQuerySet`, never written by a client.
        self.assertFalse({"date_published", "update_date"} & set(schema.model_fields))
